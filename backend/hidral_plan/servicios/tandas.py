"""Gestión de tandas: eliminar una tanda completa, archivarla y cambiar su semana.

Eliminar borra todo lo que salió de su documento (aparatos, bultos, OF, operaciones, líneas,
dependencias y asignaciones en cualquier plan) y el propio documento cuando ya no lo usa nada
más, de modo que el mismo PDF se puede volver a importar. Si en planta ya se ha fichado trabajo
de la tanda no se elimina (se perdería la trazabilidad de lo fabricado): se archiva.
"""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import delete, or_, select, update
from sqlalchemy.orm import Session

from ..modelos import (
    Aparato,
    AsignacionPlan,
    Bulto,
    CambioPlan,
    ComponenteBulto,
    DependenciaOF,
    Documento,
    Fichaje,
    IncidenciaDatos,
    IncidenciaProduccion,
    LineaOF,
    Notificacion,
    OFAparato,
    Operacion,
    OrdenFabricacion,
    Origen,
    PaginaDocumento,
    ProgramaCNC,
    Tanda,
    TrabajoProcesamiento,
)
from ..modelos.enums import EstadoTrabajo
from .auditoria import auditar

ESTADO_ARCHIVADA = "ARCHIVADA"


class TandaConTrabajo(Exception):
    """La tanda tiene fichajes: no se puede eliminar sin perder la trazabilidad."""


def _ids(s: Session, consulta) -> list[int]:
    return [i for (i,) in s.execute(consulta)]


def eliminar_tanda(s: Session, tanda_id: int, usuario: str, motivo: str | None = None) -> dict:
    t = s.get(Tanda, tanda_id)
    if t is None:
        raise LookupError("Tanda inexistente")
    of_ids = _ids(s, select(OrdenFabricacion.id).where(OrdenFabricacion.tanda_id == t.id))
    fichajes = s.scalar(select(Fichaje.id).where(Fichaje.of_id.in_(of_ids)).limit(1)) if of_ids else None
    if fichajes:
        raise TandaConTrabajo(f"La tanda {t.numero} ya tiene trabajo fichado en planta: no se puede eliminar sin perder la trazabilidad. Archívala para sacarla del plan y de las listas.")
    ap_ids = _ids(s, select(Aparato.id).where(Aparato.tanda_id == t.id))
    op_ids = _ids(s, select(Operacion.id).where(Operacion.of_id.in_(of_ids))) if of_ids else []
    docs = {d for d in [t.documento_id, *(_ids(s, select(OrdenFabricacion.documento_id).where(OrdenFabricacion.id.in_(of_ids)).distinct()) if of_ids else [])] if d}
    ap_refs = [f"aparato:{a}" for a in ap_ids]
    resumen = {"tanda": t.numero, "aparatos": len(ap_ids), "ofs": len(of_ids), "operaciones": len(op_ids)}

    borrar_ofs(s, of_ids, op_ids)
    if ap_ids:
        # referencias desde OF o líneas de otras tandas (raro, pero posible con OF compartidas)
        s.execute(update(OrdenFabricacion).where(OrdenFabricacion.aparato_id.in_(ap_ids)).values(aparato_id=None))
        s.execute(update(LineaOF).where(LineaOF.aparato_id.in_(ap_ids)).values(aparato_id=None))
        s.execute(delete(OFAparato).where(OFAparato.aparato_id.in_(ap_ids)))
        bultos = _ids(s, select(Bulto.id).where(Bulto.aparato_id.in_(ap_ids)))
        if bultos:
            s.execute(delete(ComponenteBulto).where(ComponenteBulto.bulto_id.in_(bultos)))
            s.execute(update(Bulto).where(Bulto.id.in_(bultos)).values(padre_id=None))
            s.execute(delete(Bulto).where(Bulto.id.in_(bultos)))
        s.execute(delete(Origen).where(Origen.entidad_tipo == "APARATO", Origen.entidad_id.in_(ap_ids)))
        s.execute(delete(Notificacion).where(Notificacion.referencia.in_(ap_refs)))
    if of_ids:
        s.execute(delete(OrdenFabricacion).where(OrdenFabricacion.id.in_(of_ids)))
    if ap_ids:
        s.execute(delete(Aparato).where(Aparato.id.in_(ap_ids)))
    s.execute(delete(Origen).where(Origen.entidad_tipo == "TANDA", Origen.entidad_id == t.id))
    numero = t.numero
    s.expire(t)
    s.delete(t)
    s.flush()

    # documentos que ya no usa nada: fuera, para poder volver a importar el mismo PDF
    borrados = []
    for d_id in sorted(docs):
        sigue = s.scalar(select(Tanda.id).where(Tanda.documento_id == d_id).limit(1)) or s.scalar(select(OrdenFabricacion.id).where(OrdenFabricacion.documento_id == d_id).limit(1))
        if not sigue:
            borrados.append(eliminar_documento(s, d_id))
    resumen["documentos"] = [b for b in borrados if b]
    auditar(s, usuario, "ELIMINAR_TANDA", "TANDA", numero, antes=resumen, motivo=motivo)
    return resumen


def borrar_ofs(s: Session, of_ids: list[int], op_ids: list[int] | None = None) -> None:
    """Borra lo que cuelga de unas OF (operaciones, líneas, dependencias, asignaciones…), no las OF."""
    if op_ids is None:
        op_ids = _ids(s, select(Operacion.id).where(Operacion.of_id.in_(of_ids))) if of_ids else []
    if op_ids:
        s.execute(delete(AsignacionPlan).where(AsignacionPlan.operacion_id.in_(op_ids)))
        s.execute(update(CambioPlan).where(CambioPlan.operacion_id.in_(op_ids)).values(operacion_id=None))
        s.execute(update(IncidenciaProduccion).where(IncidenciaProduccion.operacion_id.in_(op_ids)).values(operacion_id=None))
        s.execute(update(Operacion).where(Operacion.operacion_anterior_id.in_(op_ids)).values(operacion_anterior_id=None))
    if of_ids:
        s.execute(delete(AsignacionPlan).where(AsignacionPlan.of_id.in_(of_ids)))
        s.execute(update(IncidenciaProduccion).where(IncidenciaProduccion.of_id.in_(of_ids)).values(of_id=None))
        s.execute(update(Bulto).where(Bulto.of_id.in_(of_ids)).values(of_id=None))
        s.execute(delete(ProgramaCNC).where(ProgramaCNC.of_id.in_(of_ids)))
        s.execute(delete(DependenciaOF).where(or_(DependenciaOF.of_origen_id.in_(of_ids), DependenciaOF.of_destino_id.in_(of_ids))))
        s.execute(delete(LineaOF).where(LineaOF.of_id.in_(of_ids)))
        s.execute(delete(OFAparato).where(OFAparato.of_id.in_(of_ids)))
        s.execute(delete(Operacion).where(Operacion.of_id.in_(of_ids)))
        s.execute(delete(Origen).where(Origen.entidad_tipo == "OF", Origen.entidad_id.in_(of_ids)))


def eliminar_documento(s: Session, doc_id: int) -> str | None:
    d = s.get(Documento, doc_id)
    if d is None:
        return None
    activo = s.scalar(select(TrabajoProcesamiento.id).where(TrabajoProcesamiento.documento_id == d.id, TrabajoProcesamiento.estado.in_([EstadoTrabajo.EN_COLA, EstadoTrabajo.PROCESANDO])).limit(1))
    if activo:
        raise ValueError(f"El documento {d.nombre} se está procesando: espera a que termine o cancélalo")
    s.execute(update(Documento).where(Documento.documento_anterior_id == d.id).values(documento_anterior_id=None))
    s.execute(delete(IncidenciaDatos).where(IncidenciaDatos.documento_id == d.id))
    s.execute(delete(Origen).where(Origen.documento_id == d.id))
    s.execute(delete(PaginaDocumento).where(PaginaDocumento.documento_id == d.id))
    s.execute(delete(TrabajoProcesamiento).where(TrabajoProcesamiento.documento_id == d.id))
    nombre, ruta = d.nombre, d.ruta_almacen
    s.delete(d)
    s.flush()
    # el fichero se comparte por hash: solo se borra si ningún otro documento lo usa
    if ruta and not s.scalar(select(Documento.id).where(Documento.ruta_almacen == ruta).limit(1)):
        try:
            Path(ruta).unlink(missing_ok=True)
        except OSError:
            pass
    return nombre


def cambiar_semana(s: Session, tanda_id: int, semana: str, usuario: str, motivo: str | None = None, aparato_id: int | None = None) -> dict:
    """Mueve la semana de fabricación de una tanda (o de un solo aparato) y la de sus OF."""
    if not (len(semana) == 6 and semana.isdigit() and 1 <= int(semana[4:]) <= 53):
        raise ValueError("La semana va en formato AAAASS, por ejemplo 202641")
    t = s.get(Tanda, tanda_id)
    if t is None:
        raise LookupError("Tanda inexistente")
    aparatos = [a for a in t.aparatos if aparato_id is None or a.id == aparato_id]
    if aparato_id is not None and not aparatos:
        raise LookupError("El aparato no es de esta tanda")
    antes = {a.referencia: a.semana_codigo for a in aparatos}
    for a in aparatos:
        a.semana_codigo = semana
    if aparato_id is None:
        antes["tanda"] = t.semana_codigo
        t.semana_codigo = semana
        of_ids = _ids(s, select(OrdenFabricacion.id).where(OrdenFabricacion.tanda_id == t.id))
    else:
        of_ids = _ids(s, select(OFAparato.of_id).where(OFAparato.aparato_id == aparato_id))
    if of_ids:
        s.execute(update(OrdenFabricacion).where(OrdenFabricacion.id.in_(of_ids)).values(semana_codigo=semana))
    ref = aparatos[0].referencia if aparato_id is not None else t.numero
    auditar(s, usuario, "CAMBIAR_SEMANA", "APARATO" if aparato_id is not None else "TANDA", ref, antes=antes, despues={"semana": semana, "ofs": len(of_ids)}, motivo=motivo)
    return {"semana": semana, "aparatos": len(aparatos), "ofs": len(of_ids)}
