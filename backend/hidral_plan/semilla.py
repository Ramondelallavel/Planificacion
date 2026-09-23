"""Carga de la configuración de fábrica desde YAML (idempotente: actualiza por código).

    python -m hidral_plan.semilla config/fabrica_ejemplo.yaml [--ejemplo]

Con --ejemplo todo lo cargado (tiempos, reglas) queda marcado como EJEMPLO.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import yaml
from sqlalchemy import select
from sqlalchemy.orm import Session

from .db import crear_tablas, sesion
from .modelos import (
    Cualificacion,
    Operario,
    Recurso,
    ReglaDependencia,
    Seccion,
    TiempoEstandar,
    Turno,
    Usuario,
)
from .modelos.enums import Fuente
from .seguridad import hash_clave
from .servicios.auditoria import auditar


def cargar_configuracion(s: Session, datos: dict, ejemplo: bool, usuario: str = "sistema") -> dict:
    n = {"secciones": 0, "turnos": 0, "recursos": 0, "operarios": 0, "tiempos": 0, "reglas": 0, "usuarios": 0}
    for d in datos.get("secciones", []):
        sec = s.get(Seccion, d["codigo"]) or Seccion(codigo=d["codigo"])
        sec.codigo_completo = d.get("codigo_completo")
        sec.nombre = d.get("nombre")
        sec.flujo = d.get("flujo", "NORMAL")
        sec.requiere_programacion = bool(d.get("requiere_programacion", False))
        sec.conocida = True
        sec.fuente = Fuente.CONFIG_FABRICA
        s.add(sec)
        n["secciones"] += 1
    for d in datos.get("turnos", []):
        t = s.get(Turno, d["codigo"]) or Turno(codigo=d["codigo"])
        t.nombre, t.hora_inicio, t.hora_fin = d["nombre"], d["hora_inicio"], d["hora_fin"]
        t.dias_semana = d.get("dias_semana", [0, 1, 2, 3, 4])
        t.pausas = d.get("pausas")
        s.add(t)
        n["turnos"] += 1
    s.flush()
    for d in datos.get("recursos", []):
        r = s.scalar(select(Recurso).where(Recurso.codigo == d["codigo"])) or Recurso(codigo=d["codigo"])
        r.nombre = d["nombre"]
        r.tipo = d.get("tipo", "PUESTO")
        r.seccion_codigo = d.get("seccion")
        r.capacidad = int(d.get("capacidad", 1))
        r.operaciones = d.get("operaciones")
        r.alias = d.get("alias")
        r.grupos_hf = d.get("grupos_hf")
        r.turnos = d.get("turnos")
        r.requiere_operario = bool(d.get("requiere_operario", True))
        r.restricciones = d.get("restricciones")
        r.activo = True
        s.add(r)
        n["recursos"] += 1
    for d in datos.get("operarios", []):
        o = s.scalar(select(Operario).where(Operario.codigo_empleado == d["codigo"])) or Operario(codigo_empleado=d["codigo"])
        o.nombre = d["nombre"]
        o.turno_codigo = d.get("turno")
        o.seccion_codigo = d.get("seccion")
        o.activo = True
        o.cualificaciones = [Cualificacion(recurso_codigo=rc, nivel=2) for rc in d.get("recursos", [])] + [
            Cualificacion(tipo_operacion=tp, nivel=2) for tp in d.get("operaciones", [])
        ]
        s.add(o)
        n["operarios"] += 1
    s.flush()
    if datos.get("tiempos_estandar"):
        # nueva versión de los tiempos de configuración; los anteriores quedan como histórico
        previos = list(s.scalars(select(TiempoEstandar).where(TiempoEstandar.vigente.is_(True), TiempoEstandar.fuente == Fuente.CONFIG_FABRICA)))
        version = max((p.version for p in previos), default=0) + 1
        for p in previos:
            p.vigente = False
        for d in datos["tiempos_estandar"]:
            s.add(
                TiempoEstandar(
                    seccion_codigo=d["seccion"],
                    grupo_hf=d.get("grupo_hf"),
                    articulo_codigo=d.get("articulo"),
                    tipo_operacion=d.get("tipo_operacion"),
                    minutos_preparacion=float(d.get("minutos_preparacion", 0)),
                    minutos_por_unidad=float(d.get("minutos_por_unidad", 0)),
                    minutos_por_linea=float(d.get("minutos_por_linea", 0)),
                    fuente=Fuente.CONFIG_FABRICA,
                    es_ejemplo=ejemplo,
                    version=version,
                    vigente=True,
                    creado_por=usuario,
                    notas="Valor de ejemplo, sustituir por el real" if ejemplo else None,
                )
            )
            n["tiempos"] += 1
    for d in datos.get("reglas_dependencia", []):
        existe = s.scalar(select(ReglaDependencia).where(ReglaDependencia.grupo_hf_origen == d["grupo_hf_origen"], ReglaDependencia.grupo_hf_destino == d["grupo_hf_destino"]))
        r = existe or ReglaDependencia(grupo_hf_origen=d["grupo_hf_origen"], grupo_hf_destino=d["grupo_hf_destino"])
        r.mismo_aparato = bool(d.get("mismo_aparato", True))
        r.descripcion = d.get("descripcion")
        r.es_ejemplo = ejemplo
        r.activa = True
        s.add(r)
        n["reglas"] += 1
    clave_demo = os.environ.get("HIDRAL_CLAVE_DEMO", "hidral")
    for d in datos.get("usuarios", []):
        u = s.scalar(select(Usuario).where(Usuario.usuario == d["usuario"]))
        if u is None:
            u = Usuario(usuario=d["usuario"], nombre=d["nombre"], rol=d["rol"], hash_clave=hash_clave(d.get("clave", clave_demo)))
        u.nombre, u.rol = d["nombre"], d["rol"]
        if d.get("operario"):
            op = s.scalar(select(Operario).where(Operario.codigo_empleado == d["operario"]))
            u.operario_id = op.id if op else None
        s.add(u)
        n["usuarios"] += 1
    auditar(s, usuario, "CARGA_CONFIGURACION_FABRICA", "CONFIGURACION", None, despues={**n, "ejemplo": ejemplo})
    return n


def main(argv: list[str]) -> None:
    if not argv:
        print(__doc__)
        sys.exit(1)
    ruta = Path(argv[0])
    ejemplo = "--ejemplo" in argv or "ejemplo" in ruta.name
    crear_tablas()
    with sesion() as s:
        n = cargar_configuracion(s, yaml.safe_load(ruta.read_text(encoding="utf-8")), ejemplo)
    print(f"Configuración cargada ({'EJEMPLO' if ejemplo else 'real'}): {n}")


if __name__ == "__main__":
    main(sys.argv[1:])
