"""Adaptadores de integración. Interfaz común + implementación por CSV.

Columnas esperadas (se pueden renombrar con `mapeo_columnas`):
  ORTEMS:     of, prioridad, semana, inicio, fin, estado
  MRP:        of, material_disponible (S/N), fecha_material, estado, [operacion, secuencia, seccion, minutos]
  TEAMCENTER: articulo, revision, descripcion, plano, url
"""

from __future__ import annotations

import csv
import io
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..ingesta.normalizacion import normalizar_semana_larga, partes_articulo
from ..modelos import Articulo, IncidenciaDatos, Operacion, OrdenFabricacion, Origen
from ..modelos.enums import EstadoOperacion, Fuente, Severidad
from ..servicios.auditoria import auditar


@dataclass
class RegistroExterno:
    fila: int
    datos: dict[str, str]


@dataclass
class ResultadoImportacion:
    sistema: str
    filas: int = 0
    actualizadas: int = 0
    sin_correspondencia: list[str] = field(default_factory=list)
    conflictos: list[str] = field(default_factory=list)
    errores: list[str] = field(default_factory=list)

    def a_dict(self) -> dict:
        return {
            "sistema": self.sistema, "filas": self.filas, "actualizadas": self.actualizadas,
            "sin_correspondencia": self.sin_correspondencia[:100], "conflictos": self.conflictos[:100], "errores": self.errores[:100],
        }


class Adaptador(Protocol):
    sistema: str

    def registros(self) -> Iterable[RegistroExterno]: ...


class AdaptadorCSV:
    def __init__(self, sistema: str, contenido: str, mapeo_columnas: dict[str, str] | None = None) -> None:
        self.sistema = sistema
        self.contenido = contenido
        self.mapeo = {k.lower(): v for k, v in (mapeo_columnas or {}).items()}

    def registros(self) -> Iterator[RegistroExterno]:
        muestra = self.contenido[:2048]
        try:
            dialecto = csv.Sniffer().sniff(muestra, delimiters=";,\t")
        except csv.Error:
            dialecto = csv.excel
        lector = csv.DictReader(io.StringIO(self.contenido), dialect=dialecto)
        for i, fila in enumerate(lector, start=2):
            datos = {}
            for k, v in fila.items():
                if k is None:
                    continue
                clave = self.mapeo.get(k.strip().lower(), k.strip().lower())
                datos[clave] = (v or "").strip()
            yield RegistroExterno(i, datos)


def _fecha(txt: str | None) -> datetime | None:
    if not txt:
        return None
    for fmt in ("%Y-%m-%dT%H:%M", "%Y-%m-%d %H:%M", "%Y-%m-%d", "%d/%m/%Y %H:%M", "%d/%m/%Y"):
        try:
            return datetime.strptime(txt, fmt)
        except ValueError:
            continue
    return None


def _origen(s: Session, entidad: str, entidad_id: int, campo: str, fuente: str, detalle: str) -> None:
    s.add(Origen(entidad_tipo=entidad, entidad_id=entidad_id, campo=campo, fuente=fuente, detalle=detalle[:240]))


def importar_ortems(s: Session, adaptador: Adaptador, usuario: str) -> ResultadoImportacion:
    r = ResultadoImportacion("ORTEMS")
    for reg in adaptador.registros():
        r.filas += 1
        d = reg.datos
        numero = d.get("of")
        of = s.scalar(select(OrdenFabricacion).where(OrdenFabricacion.numero == numero)) if numero else None
        if of is None:
            r.sin_correspondencia.append(f"fila {reg.fila}: OF {numero or '?'} no existe en el sistema")
            continue
        if d.get("prioridad"):
            try:
                of.prioridad_ortems = float(d["prioridad"].replace(",", "."))
                _origen(s, "OF", of.id, "prioridad_ortems", Fuente.ORTEMS, f"fila {reg.fila}")
            except ValueError:
                r.errores.append(f"fila {reg.fila}: prioridad '{d['prioridad']}' no numérica")
        semana = normalizar_semana_larga(d.get("semana", "")) if d.get("semana") else None
        if semana:
            if of.semana_codigo and of.semana_codigo != semana:
                r.conflictos.append(f"OF {of.numero}: semana PDF {of.semana_codigo} ≠ ORTEMS {semana} (maestro: ORTEMS)")
                s.add(
                    IncidenciaDatos(
                        documento_id=of.documento_id, tipo="SEMANA_INCOHERENTE_FUENTES", severidad=Severidad.ADVERTENCIA,
                        mensaje=f"OF {of.numero}: el PDF indica semana {of.semana_codigo} y ORTEMS {semana}. Se aplica ORTEMS (sistema maestro de fechas).",
                        entidad_tipo="OF", entidad_ref=of.numero, alternativas=[of.semana_codigo, semana],
                    )
                )
            of.semana_codigo = semana
            _origen(s, "OF", of.id, "semana_codigo", Fuente.ORTEMS, f"fila {reg.fila}")
        r.actualizadas += 1
    auditar(s, usuario, "IMPORTACION_ORTEMS", "INTEGRACION", "ORTEMS", despues=r.a_dict())
    return r


def importar_mrp(s: Session, adaptador: Adaptador, usuario: str) -> ResultadoImportacion:
    r = ResultadoImportacion("MRP")
    rutas: dict[int, list[dict]] = {}
    for reg in adaptador.registros():
        r.filas += 1
        d = reg.datos
        numero = d.get("of")
        of = s.scalar(select(OrdenFabricacion).where(OrdenFabricacion.numero == numero)) if numero else None
        if of is None:
            r.sin_correspondencia.append(f"fila {reg.fila}: OF {numero or '?'} no existe (¿OF de MRP aún no incluida en ninguna tanda?)")
            continue
        md = d.get("material_disponible", "").upper()
        if md in ("S", "SI", "SÍ", "1", "TRUE"):
            of.material_disponible, of.material_disponible_desde = True, None
            _origen(s, "OF", of.id, "material_disponible", Fuente.MRP, f"fila {reg.fila}")
        elif md in ("N", "NO", "0", "FALSE"):
            of.material_disponible = False
            of.material_disponible_desde = _fecha(d.get("fecha_material"))
            _origen(s, "OF", of.id, "material_disponible", Fuente.MRP, f"fila {reg.fila}: {d.get('fecha_material') or 'sin fecha'}")
        if d.get("operacion") and d.get("minutos"):
            try:
                rutas.setdefault(of.id, []).append(
                    {"tipo": d["operacion"].upper(), "secuencia": int(d.get("secuencia") or 10), "seccion": d.get("seccion") or of.seccion_codigo, "minutos": float(d["minutos"].replace(",", "."))}
                )
            except ValueError:
                r.errores.append(f"fila {reg.fila}: ruta con valores no numéricos")
        r.actualizadas += 1
    for of_id, pasos in rutas.items():
        of = s.get(OrdenFabricacion, of_id)
        if any(op.estado not in (EstadoOperacion.PENDIENTE, EstadoOperacion.PENDIENTE_PROGRAMACION, EstadoOperacion.PLANIFICADA, EstadoOperacion.LISTA) for op in of.operaciones):
            r.conflictos.append(f"OF {of.numero}: ya iniciada, no se sustituye su ruta")
            continue
        for op in list(of.operaciones):
            op.operacion_anterior_id = None
        s.flush()
        for op in list(of.operaciones):
            s.delete(op)
        s.flush()
        for p in sorted(pasos, key=lambda x: x["secuencia"]):
            s.add(
                Operacion(
                    of_id=of.id, secuencia=p["secuencia"], tipo=p["tipo"], descripcion=f"{p['tipo']} (ruta MRP)", seccion_codigo=p["seccion"],
                    duracion_estimada_min=p["minutos"], origen_duracion="MRP", estado=EstadoOperacion.PENDIENTE, fuente=Fuente.MRP,
                )
            )
    auditar(s, usuario, "IMPORTACION_MRP", "INTEGRACION", "MRP", despues=r.a_dict())
    return r


def importar_teamcenter(s: Session, adaptador: Adaptador, usuario: str) -> ResultadoImportacion:
    r = ResultadoImportacion("TEAMCENTER")
    for reg in adaptador.registros():
        r.filas += 1
        d = reg.datos
        codigo = d.get("articulo")
        if not codigo:
            r.errores.append(f"fila {reg.fila}: sin artículo")
            continue
        if "/" not in codigo and d.get("revision"):
            codigo = f"{codigo}/{d['revision']}"
        art = s.get(Articulo, codigo)
        if art is None:
            base, rev = partes_articulo(codigo)
            art = Articulo(codigo=codigo, codigo_base=base, revision=rev, descripcion=d.get("descripcion"), fuente=Fuente.TEAMCENTER)
            s.add(art)
        elif d.get("descripcion") and art.descripcion and d["descripcion"] != art.descripcion:
            r.conflictos.append(f"{codigo}: descripción PDF '{art.descripcion}' ≠ Teamcenter '{d['descripcion']}' (maestro técnico: Teamcenter)")
        art.datos_tecnicos = {**(art.datos_tecnicos or {}), **{k: v for k, v in d.items() if k not in ("articulo",) and v}, "fuente": "TEAMCENTER"}
        if d.get("descripcion"):
            art.descripcion = d["descripcion"]
        r.actualizadas += 1
    auditar(s, usuario, "IMPORTACION_TEAMCENTER", "INTEGRACION", "TEAMCENTER", despues=r.a_dict())
    return r


IMPORTADORES = {"ortems": importar_ortems, "mrp": importar_mrp, "teamcenter": importar_teamcenter}
