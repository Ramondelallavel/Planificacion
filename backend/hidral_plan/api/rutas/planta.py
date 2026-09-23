"""Planta: pantalla del operario, fichajes, incidencias de producción y avisos."""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from ...modelos import AsignacionPlan, Fichaje, IncidenciaProduccion, Notificacion, Operacion, Operario, Recurso
from ...planificacion import servicio as sv
from ...servicios import ejecucion as ex
from ...servicios.auditoria import auditar
from ..deps import UsuarioActual, ahora, get_sesion, requiere, usuario_actual

router = APIRouter(tags=["planta"])


def _operario_de(u: UsuarioActual, operario_id: int | None) -> int:
    if operario_id is not None and operario_id != u.operario_id:
        if not u.puede("fichar_supervisado"):
            raise HTTPException(403, "Solo puedes ver o fichar tu propio trabajo")
        return operario_id
    if u.operario_id is None:
        raise HTTPException(400, "El usuario no está vinculado a un operario: indique operario_id")
    return u.operario_id


@router.get("/operario/trabajo")
def trabajo(operario_id: int | None = None, s: Session = Depends(get_sesion), u: UsuarioActual = Depends(usuario_actual)) -> dict:
    return ex.trabajo_operario(s, _operario_de(u, operario_id), ahora())


class Iniciar(BaseModel):
    operacion_id: int
    operario_id: int | None = None
    recurso_id: int | None = None
    autorizado_por: str | None = None


@router.post("/operario/iniciar")
def iniciar(datos: Iniciar, s: Session = Depends(get_sesion), u: UsuarioActual = Depends(usuario_actual)) -> dict:
    oid = _operario_de(u, datos.operario_id)
    autorizado = None
    if datos.autorizado_por:
        if not u.puede("fichar_supervisado"):
            raise HTTPException(403, "Solo un supervisor, jefe de equipo o planificador puede autorizar un inicio con excepciones")
        autorizado = u.usuario
    return ex.iniciar(s, oid, datos.operacion_id, u.usuario, ahora(), datos.recurso_id, autorizado)


def _fichaje_propio(s: Session, fichaje_id: int, u: UsuarioActual) -> Fichaje:
    f = s.get(Fichaje, fichaje_id)
    if f is None:
        raise HTTPException(404, "Fichaje inexistente")
    if f.operario_id != u.operario_id and not u.puede("fichar_supervisado"):
        raise HTTPException(403, "No es tu fichaje")
    return f


class Pausa(BaseModel):
    motivo: str | None = None


@router.post("/operario/fichajes/{fichaje_id}/pausar")
def pausar(fichaje_id: int, datos: Pausa, s: Session = Depends(get_sesion), u: UsuarioActual = Depends(usuario_actual)) -> dict:
    _fichaje_propio(s, fichaje_id, u)
    return ex.pausar(s, fichaje_id, u.usuario, ahora(), datos.motivo)


@router.post("/operario/fichajes/{fichaje_id}/reanudar")
def reanudar(fichaje_id: int, s: Session = Depends(get_sesion), u: UsuarioActual = Depends(usuario_actual)) -> dict:
    _fichaje_propio(s, fichaje_id, u)
    return ex.reanudar(s, fichaje_id, u.usuario, ahora())


class Terminar(BaseModel):
    cantidad: float | None = None
    parcial: bool = False


@router.post("/operario/fichajes/{fichaje_id}/terminar")
def terminar(fichaje_id: int, datos: Terminar, s: Session = Depends(get_sesion), u: UsuarioActual = Depends(usuario_actual)) -> dict:
    _fichaje_propio(s, fichaje_id, u)
    return ex.terminar(s, fichaje_id, u.usuario, ahora(), datos.cantidad, datos.parcial)


class IncidenciaOperario(BaseModel):
    operacion_id: int | None = None
    tipo: str  # AVERIA | FALTA_MATERIAL | CALIDAD | OTRA
    descripcion: str
    horas_estimadas: float | None = None


@router.post("/operario/incidencia")
def incidencia_operario(datos: IncidenciaOperario, s: Session = Depends(get_sesion), u: UsuarioActual = Depends(usuario_actual)) -> dict:
    """INCIDENCIA desde la pantalla del operario: se registra y, si afecta al plan, se replanifica."""
    op = s.get(Operacion, datos.operacion_id) if datos.operacion_id else None
    recurso_id = None
    if op is not None:
        plan = sv.plan_activo(s)
        a = s.scalar(select(AsignacionPlan).where(AsignacionPlan.plan_id == plan.id, AsignacionPlan.operacion_id == op.id)) if plan else None
        abierto = s.scalar(select(Fichaje).where(Fichaje.operacion_id == op.id, Fichaje.estado.in_(["ABIERTO", "PAUSADO"])))
        recurso_id = (abierto.recurso_id if abierto else None) or (a.recurso_id if a else None)
        if abierto and abierto.estado == "ABIERTO":
            ex.pausar(s, abierto.id, u.usuario, ahora(), f"Incidencia: {datos.descripcion}")
    evento = {"tipo": datos.tipo, "descripcion": datos.descripcion, "operacion_id": op.id if op else None, "of_id": op.of_id if op else None, "recurso_id": recurso_id, "operario_id": u.operario_id}
    if datos.tipo == "AVERIA":
        if recurso_id is None:
            raise HTTPException(400, "Indique la operación para saber qué máquina está averiada")
        if datos.horas_estimadas:
            evento["horas"] = datos.horas_estimadas
    elif datos.tipo not in ("FALTA_MATERIAL",):
        evento["tipo"] = datos.tipo  # CALIDAD / OTRA: se registra sin mover el plan
        inc = IncidenciaProduccion(tipo=datos.tipo, descripcion=datos.descripcion, operacion_id=evento["operacion_id"], of_id=evento["of_id"], recurso_id=recurso_id, operario_id=u.operario_id, reportado_por=u.usuario)
        s.add(inc)
        s.flush()
        s.add(Notificacion(rol_destino="JEFE_EQUIPO", titulo=f"Incidencia {datos.tipo}", mensaje=datos.descripcion, nivel="AVISO", referencia=f"incidencia:{inc.id}"))
        auditar(s, u.usuario, "INCIDENCIA", "INCIDENCIA", inc.id, despues=evento)
        return {"incidencia_id": inc.id, "replanificado": False}
    r = sv.registrar_incidencia(s, evento, u.usuario, ahora())
    s.add(Notificacion(rol_destino="JEFE_EQUIPO", titulo=f"Incidencia {datos.tipo}", mensaje=datos.descripcion + (f"\n{r.get('resumen')}" if r.get("resumen") else ""), nivel="ALERTA", referencia=f"incidencia:{r['incidencia_id']}"))
    return r


# ------------------------------------------------------------------ incidencias (jefe de equipo)
class Incidencia(BaseModel):
    tipo: str
    descripcion: str
    recurso_id: int | None = None
    operario_id: int | None = None
    of_id: int | None = None
    operacion_id: int | None = None
    inicio: datetime | None = None
    fin: datetime | None = None
    horas: float | None = None
    minutos_extra: float | None = None
    material_desde: datetime | None = None
    prioridad: float | None = None


@router.post("/incidencias")
def registrar(datos: Incidencia, s: Session = Depends(get_sesion), u: UsuarioActual = Depends(requiere("incidencias"))) -> dict:
    return sv.registrar_incidencia(s, datos.model_dump(), u.usuario, ahora())


@router.get("/incidencias")
def listar(estado: str | None = None, s: Session = Depends(get_sesion), _: UsuarioActual = Depends(requiere("ver"))) -> list[dict]:
    q = select(IncidenciaProduccion).order_by(IncidenciaProduccion.id.desc()).limit(200)
    if estado:
        q = q.where(IncidenciaProduccion.estado == estado)
    recs = {r.id: r.codigo for r in s.scalars(select(Recurso))}
    oprs = {o.id: o.nombre for o in s.scalars(select(Operario))}
    return [
        {
            "id": i.id, "tipo": i.tipo, "descripcion": i.descripcion, "recurso": recs.get(i.recurso_id), "operario": oprs.get(i.operario_id), "of_id": i.of_id,
            "inicio": i.inicio.isoformat(), "fin_prevista": i.fin_prevista.isoformat() if i.fin_prevista else None, "fin": i.fin.isoformat() if i.fin else None,
            "estado": i.estado, "reportado_por": i.reportado_por, "impacto": i.impacto, "lote": i.lote_replanificacion,
        }
        for i in s.scalars(q)
    ]


@router.post("/incidencias/{inc_id}/cerrar")
def cerrar(inc_id: int, s: Session = Depends(get_sesion), u: UsuarioActual = Depends(requiere("incidencias"))) -> dict:
    i = s.get(IncidenciaProduccion, inc_id)
    if i is None:
        raise HTTPException(404, "Incidencia inexistente")
    i.estado, i.fin = "CERRADA", ahora()
    if i.tipo == "AVERIA" and i.recurso_id:
        r = s.get(Recurso, i.recurso_id)
        from ...modelos import ParadaRecurso

        for p in s.scalars(select(ParadaRecurso).where(ParadaRecurso.incidencia_id == i.id)):
            if p.fin is None or p.fin > i.fin:
                p.fin = i.fin
        if r:
            r.estado = "OPERATIVO"
    auditar(s, u.usuario, "CERRAR_INCIDENCIA", "INCIDENCIA", i.id)
    return {"id": i.id, "estado": i.estado}


@router.get("/notificaciones")
def notificaciones(s: Session = Depends(get_sesion), u: UsuarioActual = Depends(usuario_actual)) -> list[dict]:
    q = select(Notificacion).order_by(Notificacion.id.desc()).limit(50)
    if u.operario_id and not u.puede("ver"):
        q = q.where(Notificacion.operario_id == u.operario_id)
    elif not u.operario_id:
        q = q.where((Notificacion.rol_destino.is_not(None)) | (Notificacion.operario_id.is_not(None)))
    return [{"id": n.id, "fecha": n.fecha.isoformat(), "titulo": n.titulo, "mensaje": n.mensaje, "nivel": n.nivel, "leida": n.leida, "operario_id": n.operario_id, "rol": n.rol_destino} for n in s.scalars(q)]


@router.post("/notificaciones/{nid}/leida")
def leida(nid: int, s: Session = Depends(get_sesion), _: UsuarioActual = Depends(usuario_actual)) -> dict:
    n = s.get(Notificacion, nid)
    if n:
        n.leida = True
    return {"id": nid}
