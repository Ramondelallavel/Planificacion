"""Validación de integridad tras importar un documento (punto 35-36 del pliego).

No se inventan soluciones: cada problema queda como incidencia de datos con severidad,
página, entidad y texto de origen para su revisión.
"""

from __future__ import annotations

from collections import Counter, defaultdict

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..modelos import (
    Aparato,
    Bulto,
    IncidenciaDatos,
    LineaOF,
    OFAparato,
    OrdenFabricacion,
    Tanda,
)
from ..modelos.enums import EstadoIncidenciaDatos, Severidad


def _inc(
    s: Session, doc: int, tipo: str, sev: str, msg: str, entidad: str, ref: str | None, pagina: int | None = None, alternativas: list | None = None, texto: str | None = None
) -> None:
    s.add(
        IncidenciaDatos(
            documento_id=doc, tipo=tipo, severidad=sev, mensaje=msg, entidad_tipo=entidad, entidad_ref=ref, pagina=pagina, alternativas=alternativas, texto_origen=texto
        )
    )


def completar_semanas(s: Session, documento_id: int, tanda_id: int) -> None:
    """Semana de OF, aparato y tanda a partir de lo que dicen las hojas (sin suponer nada)."""
    ofs = list(s.scalars(select(OrdenFabricacion).where(OrdenFabricacion.documento_id == documento_id)))
    semanas_linea: dict[int, Counter] = defaultdict(Counter)
    for of_id, semana in s.execute(select(LineaOF.of_id, LineaOF.semana_codigo).where(LineaOF.of_id.in_([o.id for o in ofs]), LineaOF.semana_codigo.is_not(None))):
        semanas_linea[of_id][semana] += 1
    aparatos = {a.id: a for a in s.scalars(select(Aparato).where(Aparato.tanda_id == tanda_id))}
    for of in ofs:
        c = semanas_linea.get(of.id)
        if not of.semana_codigo and c:
            if len(c) > 1:
                of.semana_codigo = min(c)
                _inc(
                    s,
                    documento_id,
                    "SEMANAS_DISTINTAS_EN_OF",
                    Severidad.INFO,
                    f"La OF {of.numero} agrupa piezas de semanas {sorted(c)}; se toma la más temprana ({of.semana_codigo}) como objetivo de la OF.",
                    "OF",
                    of.numero,
                    (of.paginas or [None])[0],
                    alternativas=sorted(c),
                )
            else:
                of.semana_codigo = next(iter(c))
        if not of.semana_codigo and of.aparato_id and aparatos.get(of.aparato_id) and aparatos[of.aparato_id].semana_codigo:
            of.semana_codigo = aparatos[of.aparato_id].semana_codigo
        if not of.semana_codigo and of.tiene_hoja:
            _inc(s, documento_id, "SEMANA_AUSENTE", Severidad.ADVERTENCIA, f"OF {of.numero}: semana de fabricación DATO NO DISPONIBLE.", "OF", of.numero, (of.paginas or [None])[0])
    for ap in aparatos.values():
        if not ap.semana_codigo:
            _inc(s, documento_id, "SEMANA_AUSENTE", Severidad.ADVERTENCIA, f"Aparato {ap.referencia}: semana de fabricación DATO NO DISPONIBLE.", "APARATO", ap.numero_control)
    tanda = s.get(Tanda, tanda_id)
    semanas = sorted({a.semana_codigo for a in aparatos.values() if a.semana_codigo})
    if tanda and semanas:
        tanda.semana_codigo = semanas[0]
        if len(semanas) > 1:
            _inc(
                s,
                documento_id,
                "SEMANAS_DISTINTAS_EN_TANDA",
                Severidad.INFO,
                f"La tanda {tanda.numero} tiene aparatos con semanas {semanas}; la tanda toma la más temprana.",
                "TANDA",
                tanda.numero,
                alternativas=semanas,
            )


def validar(s: Session, documento_id: int, tanda_id: int | None) -> None:
    if tanda_id is None:
        return
    aparatos = list(s.scalars(select(Aparato).where(Aparato.tanda_id == tanda_id)))
    con_of = {a for (a,) in s.execute(select(OFAparato.aparato_id).where(OFAparato.aparato_id.in_([a.id for a in aparatos])).distinct())}
    bultos_por_ap: dict[int, list[Bulto]] = defaultdict(list)
    for b in s.scalars(select(Bulto).where(Bulto.aparato_id.in_([a.id for a in aparatos]))):
        bultos_por_ap[b.aparato_id].append(b)
    alguno_con_bultos = any(bultos_por_ap.values())
    for ap in aparatos:
        if ap.id not in con_of:
            _inc(s, documento_id, "APARATO_SIN_OF", Severidad.ERROR, f"El aparato {ap.referencia} aparece en el documento pero no tiene ninguna OF.", "APARATO", ap.numero_control)
        bultos = bultos_por_ap.get(ap.id, [])
        if alguno_con_bultos and not bultos:
            _inc(
                s,
                documento_id,
                "APARATO_SIN_BULTO",
                Severidad.ADVERTENCIA,
                f"El aparato {ap.referencia} no tiene lista de bultos en el documento (otros aparatos sí).",
                "APARATO",
                ap.numero_control,
            )
        fuentes_ap = {f.split(" ")[0] for b in bultos for f in (b.fuentes or [])}
        if {"LISTA_MATERIALES", "PACKING_LIST"} <= fuentes_ap:
            for b in bultos:
                if b.padre_id is None:
                    f = {x.split(" ")[0] for x in (b.fuentes or [])}
                    if not ({"LISTA_MATERIALES", "PACKING_LIST"} <= f):
                        _inc(
                            s,
                            documento_id,
                            "BULTO_SOLO_EN_UNA_FUENTE",
                            Severidad.ADVERTENCIA,
                            f"Bulto {b.numero} del aparato {ap.referencia} solo aparece en {', '.join(sorted(f))}.",
                            "BULTO",
                            f"{ap.numero_control}/{b.numero}",
                        )
        for b in bultos:
            if b.padre_id is None and b.descripcion is None and b.codigo is None:
                _inc(
                    s,
                    documento_id,
                    "BULTO_SIN_DESCRIPCION",
                    Severidad.ADVERTENCIA,
                    f"Bulto {b.numero} del aparato {ap.referencia} referenciado sin descripción en listas.",
                    "BULTO",
                    f"{ap.numero_control}/{b.numero}",
                )

    # Referencias duplicadas: identificadores de pieza que deberían ser únicos
    ofs_doc = select(OrdenFabricacion.id).where(OrdenFabricacion.documento_id == documento_id)
    duplicadas = s.execute(
        select(LineaOF.id_pieza, func.count(LineaOF.id))
        .where(LineaOF.of_id.in_(ofs_doc), LineaOF.id_pieza.is_not(None))
        .group_by(LineaOF.id_pieza)
        .having(func.count(LineaOF.id) > 1)
    ).all()
    for id_pieza, n in duplicadas:
        _inc(s, documento_id, "REFERENCIA_DUPLICADA", Severidad.ADVERTENCIA, f"El identificador de pieza {id_pieza} aparece {n} veces.", "PIEZA", id_pieza)
    pos_dup = s.execute(
        select(LineaOF.of_id, LineaOF.posicion, func.count(LineaOF.id))
        .where(LineaOF.of_id.in_(ofs_doc), LineaOF.posicion.is_not(None))
        .group_by(LineaOF.of_id, LineaOF.posicion)
        .having(func.count(LineaOF.id) > 1)
    ).all()
    for of_id, pos, n in pos_dup:
        of = s.get(OrdenFabricacion, of_id)
        _inc(
            s,
            documento_id,
            "REFERENCIA_DUPLICADA",
            Severidad.ADVERTENCIA,
            f"Posición {pos} repetida {n} veces en la OF {of.numero if of else of_id}.",
            "OF",
            of.numero if of else None,
        )
    # OF con hoja pero sin ninguna línea
    vacias = s.execute(
        select(OrdenFabricacion.numero, OrdenFabricacion.paginas).where(
            OrdenFabricacion.documento_id == documento_id, OrdenFabricacion.tiene_hoja.is_(True), ~OrdenFabricacion.id.in_(select(LineaOF.of_id).distinct())
        )
    ).all()
    for numero, paginas in vacias:
        _inc(s, documento_id, "OF_SIN_LINEAS", Severidad.ADVERTENCIA, f"La OF {numero} tiene cabecera pero ninguna línea interpretada.", "OF", numero, (paginas or [None])[0])


def resumen_documento(s: Session, documento_id: int, tanda_id: int | None) -> dict:
    ofs_doc = select(OrdenFabricacion.id).where(OrdenFabricacion.documento_id == documento_id)
    sev = dict(
        s.execute(
            select(IncidenciaDatos.severidad, func.count(IncidenciaDatos.id))
            .where(IncidenciaDatos.documento_id == documento_id, IncidenciaDatos.estado == EstadoIncidenciaDatos.ABIERTA)
            .group_by(IncidenciaDatos.severidad)
        ).all()
    )
    tipos = dict(s.execute(select(IncidenciaDatos.tipo, func.count(IncidenciaDatos.id)).where(IncidenciaDatos.documento_id == documento_id).group_by(IncidenciaDatos.tipo)).all())
    aparatos = s.scalar(select(func.count(Aparato.id)).where(Aparato.tanda_id == tanda_id)) if tanda_id else 0
    return {
        "ofs": s.scalar(select(func.count(OrdenFabricacion.id)).where(OrdenFabricacion.documento_id == documento_id, OrdenFabricacion.tiene_hoja.is_(True))),
        "ofs_referenciadas_sin_hoja": s.scalar(
            select(func.count(OrdenFabricacion.id)).where(OrdenFabricacion.documento_id == documento_id, OrdenFabricacion.tiene_hoja.is_(False))
        ),
        "lineas": s.scalar(select(func.count(LineaOF.id)).where(LineaOF.of_id.in_(ofs_doc))),
        "aparatos": aparatos,
        "bultos": s.scalar(select(func.count(Bulto.id)).where(Bulto.aparato_id.in_(select(Aparato.id).where(Aparato.tanda_id == tanda_id)))) if tanda_id else 0,
        "secciones": s.scalar(
            select(func.count(func.distinct(OrdenFabricacion.seccion_codigo))).where(OrdenFabricacion.documento_id == documento_id, OrdenFabricacion.tiene_hoja.is_(True))
        ),
        "criticas": sev.get(Severidad.CRITICA, 0),
        "errores": sev.get(Severidad.ERROR, 0),
        "advertencias": sev.get(Severidad.ADVERTENCIA, 0),
        "informativas": sev.get(Severidad.INFO, 0),
        "datos_sin_identificar": tipos.get("FILA_NO_INTERPRETADA", 0) + tipos.get("PAGINA_NO_CLASIFICADA", 0) + tipos.get("PAGINA_SIN_TEXTO", 0),
        "relaciones_incompletas": tipos.get("OF_SIN_APARATO", 0)
        + tipos.get("APARATO_SIN_OF", 0)
        + tipos.get("PIEZA_SIN_DESTINO", 0)
        + tipos.get("RELACION_AMBIGUA", 0)
        + tipos.get("OF_REFERENCIADA_SIN_HOJA", 0),
        "por_tipo": tipos,
    }
