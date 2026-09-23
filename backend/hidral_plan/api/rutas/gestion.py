"""Auditoría, integraciones (ORTEMS / MRP / Teamcenter) y aprendizaje de tiempos."""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from ...integraciones import SISTEMA_MAESTRO
from ...integraciones.adaptadores import IMPORTADORES, AdaptadorCSV
from ...modelos import Auditoria, EstimacionPropuesta, TiempoEstandar
from ...servicios import ejecucion as ex
from ..deps import UsuarioActual, get_sesion, requiere

router = APIRouter(tags=["gestión"])


@router.get("/auditoria")
def auditoria(
    accion: str | None = None, entidad_tipo: str | None = None, entidad_id: str | None = None, usuario: str | None = None, desde: datetime | None = None,
    limite: int = 200, s: Session = Depends(get_sesion), _: UsuarioActual = Depends(requiere("ver")),
) -> list[dict]:
    q = select(Auditoria).order_by(Auditoria.id.desc())
    if accion:
        q = q.where(Auditoria.accion == accion)
    if entidad_tipo:
        q = q.where(Auditoria.entidad_tipo == entidad_tipo)
    if entidad_id:
        q = q.where(Auditoria.entidad_id == entidad_id)
    if usuario:
        q = q.where(Auditoria.usuario == usuario)
    if desde:
        q = q.where(Auditoria.fecha >= desde)
    return [
        {"id": a.id, "fecha": a.fecha.isoformat(), "usuario": a.usuario, "accion": a.accion, "entidad_tipo": a.entidad_tipo, "entidad_id": a.entidad_id, "antes": a.antes, "despues": a.despues, "motivo": a.motivo, "automatica": a.automatica}
        for a in s.scalars(q.limit(min(limite, 2000)))
    ]


@router.get("/integraciones/sistema-maestro")
def maestro(_: UsuarioActual = Depends(requiere("ver"))) -> dict:
    return SISTEMA_MAESTRO


@router.post("/integraciones/{sistema}/importar")
async def importar(
    sistema: str, fichero: UploadFile = File(...), mapeo_columnas: str | None = Form(None), s: Session = Depends(get_sesion), u: UsuarioActual = Depends(requiere("configurar")),
) -> dict:
    """Importa una exportación CSV del sistema indicado (ortems | mrp | teamcenter)."""
    if sistema not in IMPORTADORES:
        raise HTTPException(404, f"Sistema desconocido: {sistema}")
    import json

    contenido = (await fichero.read()).decode("utf-8-sig", errors="replace")
    mapeo = json.loads(mapeo_columnas) if mapeo_columnas else None
    return IMPORTADORES[sistema](s, AdaptadorCSV(sistema.upper(), contenido, mapeo), u.usuario).a_dict()


@router.post("/aprendizaje/proponer")
def proponer(s: Session = Depends(get_sesion), _: UsuarioActual = Depends(requiere("aprobar_estimaciones"))) -> list[dict]:
    return ex.proponer_estimaciones(s)


@router.get("/aprendizaje/propuestas")
def propuestas(s: Session = Depends(get_sesion), _: UsuarioActual = Depends(requiere("ver"))) -> list[dict]:
    salida = []
    for p in s.scalars(select(EstimacionPropuesta).order_by(EstimacionPropuesta.id.desc()).limit(100)):
        te = s.get(TiempoEstandar, p.tiempo_estandar_id)
        salida.append(
            {
                "id": p.id, "estado": p.estado, "muestras": p.muestras, "ratio": p.ratio_real_planificado, "actual": p.minutos_por_unidad_actual,
                "propuesto": p.minutos_por_unidad_propuesto, "explicacion": p.explicacion, "creada": p.creada.isoformat(), "decidida_por": p.decidida_por,
                "ambito": {"seccion": te.seccion_codigo, "grupo_hf": te.grupo_hf, "tipo_operacion": te.tipo_operacion} if te else None,
            }
        )
    return salida


class DecisionEstimacion(BaseModel):
    aprobar: bool


@router.post("/aprendizaje/propuestas/{pid}/decidir")
def decidir(pid: int, datos: DecisionEstimacion, s: Session = Depends(get_sesion), u: UsuarioActual = Depends(requiere("aprobar_estimaciones"))) -> dict:
    return ex.decidir_estimacion(s, pid, datos.aprobar, u.usuario)


@router.post("/tiempos-estandar/{te_id}/revertir")
def revertir(te_id: int, s: Session = Depends(get_sesion), u: UsuarioActual = Depends(requiere("aprobar_estimaciones"))) -> dict:
    return ex.revertir_tiempo_estandar(s, te_id, u.usuario)
