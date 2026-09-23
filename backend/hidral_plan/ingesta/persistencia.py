"""Persistencia de los registros de un bloque en una única transacción.

Claves naturales: TANDA por número, APARATO por (tanda, nº control), OF por número,
BULTO por (aparato, número). Los datos de ejecución (estados, fichajes) de una OF que ya
existía no se tocan al importar una nueva versión: solo se sustituyen sus líneas.

Solo se guardan en memoria entre bloques mapas de identificadores (unos pocos kB).
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from ..modelos import (
    Aparato,
    Articulo,
    Bulto,
    ComponenteBulto,
    IncidenciaDatos,
    LineaOF,
    OFAparato,
    OrdenFabricacion,
    Origen,
    PaginaDocumento,
    Tanda,
)
from ..modelos.enums import Fuente, Severidad
from .maquetacion import parametros_a_dict
from .normalizacion import partes_articulo
from .registros import (
    RegAparato,
    RegAviso,
    RegBulto,
    RegComponenteBulto,
    RegConsumo,
    Registro,
    RegLinea,
    RegOF,
    RegTanda,
)


@dataclass
class EstadoPersistencia:
    """Mapas de identificadores reutilizados entre bloques del mismo trabajo."""

    documento_id: int
    tanda_id: int | None = None
    tandas: dict[str, int] = field(default_factory=dict)
    aparatos: dict[tuple[int, str], int] = field(default_factory=dict)
    ofs: dict[str, int] = field(default_factory=dict)
    ofs_reiniciadas: set[str] = field(default_factory=set)
    articulos: set[str] = field(default_factory=set)
    aparatos_pendientes: list[RegAparato] = field(default_factory=list)
    bultos_pendientes: list[RegBulto] = field(default_factory=list)
    componentes_pendientes: list[RegComponenteBulto] = field(default_factory=list)
    contadores: dict[str, int] = field(default_factory=lambda: defaultdict(int))


def _aviso(s: Session, est: EstadoPersistencia, a: RegAviso) -> None:
    s.add(
        IncidenciaDatos(
            documento_id=est.documento_id,
            pagina=a.pagina,
            tipo=a.tipo,
            severidad=a.severidad,
            mensaje=a.mensaje,
            entidad_tipo=a.entidad_tipo,
            entidad_ref=a.entidad_ref,
            texto_origen=a.texto_origen,
            alternativas=a.alternativas,
        )
    )
    est.contadores[f"aviso_{a.severidad}"] += 1


def _origen(
    s: Session, est: EstadoPersistencia, tipo: str, entidad_id: int, pagina: int, bloque: int, texto: str | None, campo: str | None = None, detalle: str | None = None
) -> None:
    s.add(
        Origen(
            entidad_tipo=tipo,
            entidad_id=entidad_id,
            campo=campo,
            fuente=Fuente.PDF,
            documento_id=est.documento_id,
            pagina=pagina,
            bloque=bloque,
            texto_origen=(texto or "")[:2000],
            detalle=detalle,
        )
    )


def _tanda(s: Session, est: EstadoPersistencia, r: RegTanda, bloque: int) -> int:
    if r.numero in est.tandas:
        return est.tandas[r.numero]
    t = s.scalar(select(Tanda).where(Tanda.numero == r.numero))
    if t is None:
        t = Tanda(numero=r.numero, producto=r.producto, documento_id=est.documento_id)
        s.add(t)
        s.flush()
        _origen(s, est, "TANDA", t.id, r.pagina, bloque, r.texto_origen)
        est.contadores["tandas"] += 1
    else:
        t.documento_id = est.documento_id
        if r.producto and not t.producto:
            t.producto = r.producto
    est.tandas[r.numero] = t.id
    if est.tanda_id is None:
        est.tanda_id = t.id
    return t.id


def _aparato_id(s: Session, est: EstadoPersistencia, tanda_id: int, control: str, tipo: str | None, pagina: int, bloque: int, texto: str) -> int:
    clave = (tanda_id, control)
    if clave in est.aparatos:
        return est.aparatos[clave]
    ap = s.scalar(select(Aparato).where(Aparato.tanda_id == tanda_id, Aparato.numero_control == control))
    if ap is None:
        ap = Aparato(tanda_id=tanda_id, numero_control=control, referencia=f"{tipo}-{control}" if tipo else control, tipo=tipo)
        s.add(ap)
        s.flush()
        _origen(s, est, "APARATO", ap.id, pagina, bloque, texto)
        est.contadores["aparatos"] += 1
    est.aparatos[clave] = ap.id
    return ap.id


def _conflicto(s: Session, est: EstadoPersistencia, entidad: str, ref: str, campo: str, actual, nuevo, pagina: int, texto: str) -> None:
    _aviso(
        s,
        est,
        RegAviso(
            f"{campo.upper()}_INCOHERENTE",
            Severidad.ADVERTENCIA,
            f"{entidad} {ref}: el campo '{campo}' tiene valores distintos en el documento ('{actual}' y '{nuevo}'). Se conserva el primero; REVISIÓN NECESARIA.",
            pagina,
            texto,
            entidad,
            ref,
            alternativas=[actual, nuevo],
        ),
    )


def _aplicar_aparato(s: Session, est: EstadoPersistencia, r: RegAparato, bloque: int) -> None:
    if est.tanda_id is None:
        est.aparatos_pendientes.append(r)
        return
    ap_id = _aparato_id(s, est, est.tanda_id, r.numero_control, r.tipo, r.pagina, bloque, r.texto_origen)
    ap = s.get(Aparato, ap_id)
    assert ap is not None
    if r.tipo and (not ap.tipo or ap.referencia == ap.numero_control):
        ap.tipo = r.tipo
        ap.referencia = r.referencia or ap.referencia
    for campo in ("semana_codigo", "producto", "cliente", "su_referencia", "ffp", "embalaje"):
        nuevo = getattr(r, campo)
        if not nuevo:
            continue
        actual = getattr(ap, campo)
        if actual is None:
            setattr(ap, campo, nuevo)
            if r.fuente_detalle != "HOJA" or campo == "semana_codigo":
                _origen(
                    s,
                    est,
                    "APARATO",
                    ap.id,
                    r.pagina,
                    bloque,
                    r.texto_origen,
                    campo=campo,
                    detalle=("semana derivada de 'Sxx' + año de F. Emisión" if (campo == "semana_codigo" and r.semana_derivada) else r.fuente_detalle),
                )
        elif actual != nuevo:
            a, n = str(actual).upper().strip(), str(nuevo).upper().strip()
            if campo in ("cliente", "producto") and (a.startswith(n) or n.startswith(a)):
                # misma denominación con sufijo (p.ej. "KONE ELEVADORES, S.A." / "... (CENTRAL)"): compatible
                continue
            _conflicto(s, est, "APARATO", r.numero_control, campo, actual, nuevo, r.pagina, r.texto_origen)


def _aplicar_of(s: Session, est: EstadoPersistencia, r: RegOF, bloque: int) -> None:
    of_id = est.ofs.get(r.numero)
    of = s.get(OrdenFabricacion, of_id) if of_id else s.scalar(select(OrdenFabricacion).where(OrdenFabricacion.numero == r.numero))
    if of is None:
        of = OrdenFabricacion(numero=r.numero)
        s.add(of)
        est.contadores["ofs"] += 1
    if r.numero not in est.ofs_reiniciadas:
        # primera vez que aparece en este documento: sus líneas se sustituyen (nueva versión)
        if of.id is not None:
            s.execute(delete(LineaOF).where(LineaOF.of_id == of.id))
            s.execute(delete(OFAparato).where(OFAparato.of_id == of.id))
            of.consumos = []
        of.paginas = []
        est.ofs_reiniciadas.add(r.numero)
    of.tanda_id = est.tanda_id
    of.seccion_codigo = r.seccion_codigo or of.seccion_codigo
    of.seccion_completa = r.seccion_completa or of.seccion_completa
    of.grupo_hf = r.grupo_hf or of.grupo_hf
    of.grupo_conj = r.grupo_conj or of.grupo_conj
    of.descripcion = r.descripcion or of.descripcion
    of.modo = r.modo or of.modo
    if r.programa_codigo:
        of.programa_codigo = r.programa_codigo
        of.programa_descripcion = r.programa_descripcion
    if r.semana_codigo:
        if of.semana_codigo and of.semana_codigo != r.semana_codigo:
            _conflicto(s, est, "OF", r.numero, "semana_codigo", of.semana_codigo, r.semana_codigo, r.pagina, r.texto_origen)
        else:
            of.semana_codigo = r.semana_codigo
    of.tiene_hoja = True
    of.fuente = Fuente.PDF
    of.documento_id = est.documento_id
    of.paginas = sorted(set((of.paginas or []) + [r.pagina]))
    extra = dict(of.parametros_extra or {})
    extra["formato"] = r.formato
    if r.numero_control_titulo:
        extra["numero_control_titulo"] = r.numero_control_titulo
    if r.numero_desde_casilla:
        extra["numero_desde_casilla"] = True
    of.parametros_extra = extra
    s.flush()
    est.ofs[r.numero] = of.id
    _origen(s, est, "OF", of.id, r.pagina, bloque, r.texto_origen)


def _of_id(s: Session, est: EstadoPersistencia, numero: str) -> int | None:
    if numero in est.ofs:
        return est.ofs[numero]
    of_id = s.scalar(select(OrdenFabricacion.id).where(OrdenFabricacion.numero == numero))
    if of_id:
        est.ofs[numero] = of_id
    return of_id


def _articulo(s: Session, est: EstadoPersistencia, codigo: str | None, descripcion: str | None) -> None:
    if not codigo or codigo in est.articulos:
        return
    est.articulos.add(codigo)
    if s.get(Articulo, codigo) is None:
        base, rev = partes_articulo(codigo)
        s.add(Articulo(codigo=codigo, codigo_base=base, revision=rev, descripcion=descripcion, fuente=Fuente.PDF))


def _aplicar_linea(s: Session, est: EstadoPersistencia, r: RegLinea, bloque: int, asociaciones: dict) -> None:
    of_id = _of_id(s, est, r.of_numero)
    if of_id is None:
        _aviso(s, est, RegAviso("LINEA_SIN_OF", Severidad.ERROR, f"Línea asociada a OF {r.of_numero} inexistente.", r.pagina, r.texto_origen, "OF", r.of_numero))
        return
    ap_id = None
    if r.numero_control and est.tanda_id is not None:
        ap_id = _aparato_id(s, est, est.tanda_id, r.numero_control, r.tipo_aparato, r.pagina, bloque, r.texto_origen)
        asociaciones[(of_id, ap_id)] += 1
    s.add(
        LineaOF(
            of_id=of_id,
            tipo=r.tipo,
            articulo_codigo=r.articulo_codigo,
            articulo_descripcion=r.articulo_descripcion,
            posicion=r.posicion,
            id_pieza=r.id_pieza,
            parametros=r.parametros,
            parametros_dict=parametros_a_dict(r.parametros) or None,
            cantidad=r.cantidad,
            cantidad_texto=r.cantidad_texto,
            detalle_corte=r.detalle_corte,
            material=r.material,
            espesor_mm=r.espesor_mm,
            largo_mm=r.largo_mm,
            ancho_mm=r.ancho_mm,
            aparato_id=ap_id,
            numero_control=r.numero_control,
            semana_codigo=r.semana_codigo,
            seccion_ref=r.seccion_ref,
            orden_ref=r.orden_ref,
            orden_plegado=r.orden_plegado,
            operaciones_marcadas=r.operaciones_marcadas or None,
            pagina=r.pagina,
            texto_origen=r.texto_origen[:2000],
        )
    )
    _articulo(s, est, r.articulo_codigo, r.articulo_descripcion)
    est.contadores["lineas"] += 1


def _aplicar_consumo(s: Session, est: EstadoPersistencia, r: RegConsumo) -> None:
    of_id = _of_id(s, est, r.of_numero)
    if of_id is None:
        return
    of = s.get(OrdenFabricacion, of_id)
    assert of is not None
    of.consumos = list(of.consumos or []) + [
        {"articulo": r.articulo_codigo, "descripcion": r.descripcion, "total": r.total, "total_texto": r.total_texto, "pagina": r.pagina, "tipo": r.tipo}
    ]


def _aplicar_bulto(s: Session, est: EstadoPersistencia, r: RegBulto, bloque: int) -> None:
    if est.tanda_id is None:
        est.bultos_pendientes.append(r)
        return
    ap_id = _aparato_id(s, est, est.tanda_id, r.numero_control, None, r.pagina, bloque, r.texto_origen)
    b = s.scalar(select(Bulto).where(Bulto.aparato_id == ap_id, Bulto.numero == r.numero))
    fuente = f"{r.fuente_detalle} p.{r.pagina}"
    if b is None:
        orden = int(r.numero.split(".")[0]) * 100 + (int(r.numero.split(".")[1]) if "." in r.numero else 0) if r.numero.replace(".", "").isdigit() else 0
        b = Bulto(aparato_id=ap_id, numero=r.numero, orden=orden, fuentes=[])
        s.add(b)
        est.contadores["bultos"] += 1
    for campo in ("codigo", "descripcion", "largo_mm", "ancho_mm", "alto_mm", "peso_kg"):
        nuevo = getattr(r, campo)
        if nuevo is None:
            continue
        actual = getattr(b, campo)
        if actual is None:
            setattr(b, campo, nuevo)
        elif campo != "descripcion" and actual != nuevo:
            _conflicto(s, est, "BULTO", f"{r.numero_control}/{r.numero}", campo, actual, nuevo, r.pagina, r.texto_origen)
    if r.padre:
        padre = s.scalar(select(Bulto).where(Bulto.aparato_id == ap_id, Bulto.numero == r.padre))
        if padre is None:
            _aviso(s, est, RegAviso("BULTO_SIN_PADRE", Severidad.ADVERTENCIA, f"Sub-bulto {r.numero} sin bulto {r.padre}.", r.pagina, r.texto_origen, "APARATO", r.numero_control))
        else:
            b.padre_id = padre.id
    if r.of_numero:
        of_id = _of_id(s, est, r.of_numero)
        if of_id:
            if b.of_id and b.of_id != of_id:
                _conflicto(s, est, "BULTO", f"{r.numero_control}/{r.numero}", "of", b.of_id, of_id, r.pagina, r.texto_origen)
            else:
                b.of_id = of_id
    if fuente not in (b.fuentes or []):
        b.fuentes = list(b.fuentes or []) + [fuente]
    s.flush()


def _aplicar_componente(s: Session, est: EstadoPersistencia, r: RegComponenteBulto) -> None:
    if est.tanda_id is None:
        est.componentes_pendientes.append(r)
        return
    ap_id = est.aparatos.get((est.tanda_id, r.numero_control))
    b = s.scalar(select(Bulto).where(Bulto.aparato_id == ap_id, Bulto.numero == r.bulto_numero)) if ap_id else None
    if b is None:
        _aviso(
            s, est, RegAviso("COMPONENTE_SIN_BULTO", Severidad.ERROR, f"Componente {r.articulo_codigo} sin bulto {r.bulto_numero}.", r.pagina, None, "APARATO", r.numero_control)
        )
        return
    s.add(
        ComponenteBulto(
            bulto_id=b.id,
            articulo_codigo=r.articulo_codigo,
            descripcion=r.descripcion,
            parametros=r.parametros,
            traduccion=r.traduccion,
            cantidad=r.cantidad,
            pagina=r.pagina,
        )
    )
    _articulo(s, est, r.articulo_codigo, r.descripcion)
    est.contadores["componentes_bulto"] += 1


def persistir_bloque(s: Session, est: EstadoPersistencia, registros: list[Registro], paginas: list[dict], bloque: int) -> None:
    asociaciones: dict[tuple[int, int], int] = defaultdict(int)
    for r in registros:
        if isinstance(r, RegTanda):
            _tanda(s, est, r, bloque)
        elif isinstance(r, RegAparato):
            _aplicar_aparato(s, est, r, bloque)
        elif isinstance(r, RegOF):
            _aplicar_of(s, est, r, bloque)
        elif isinstance(r, RegLinea):
            _aplicar_linea(s, est, r, bloque, asociaciones)
        elif isinstance(r, RegConsumo):
            _aplicar_consumo(s, est, r)
        elif isinstance(r, RegBulto):
            _aplicar_bulto(s, est, r, bloque)
        elif isinstance(r, RegComponenteBulto):
            _aplicar_componente(s, est, r)
        elif isinstance(r, RegAviso):
            _aviso(s, est, r)
    s.flush()
    for (of_id, ap_id), n in asociaciones.items():
        rel = s.get(OFAparato, (of_id, ap_id))
        if rel is None:
            s.add(OFAparato(of_id=of_id, aparato_id=ap_id, lineas=n))
        else:
            rel.lineas += n
    for p in paginas:
        s.add(PaginaDocumento(documento_id=est.documento_id, bloque=bloque, **p))
    est.contadores["paginas"] += len(paginas)


def resolver_pendientes(s: Session, est: EstadoPersistencia) -> None:
    """Registros que llegaron antes de conocer la tanda (p.ej. una lista de materiales al inicio)."""
    if est.tanda_id is None:
        for r in est.aparatos_pendientes[:1]:
            _aviso(
                s,
                est,
                RegAviso(
                    "TANDA_AUSENTE",
                    Severidad.CRITICA,
                    "El documento no contiene ninguna cabecera 'TANDA': no se puede asociar aparatos ni OF.",
                    r.pagina,
                    None,
                    "DOCUMENTO",
                    str(est.documento_id),
                ),
            )
        return
    for r in est.aparatos_pendientes:
        _aplicar_aparato(s, est, r, 0)
    for r in est.bultos_pendientes:
        _aplicar_bulto(s, est, r, 0)
    for r in est.componentes_pendientes:
        _aplicar_componente(s, est, r)
    est.aparatos_pendientes.clear()
    est.bultos_pendientes.clear()
    est.componentes_pendientes.clear()
