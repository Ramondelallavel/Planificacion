"""Carga de trabajo: operaciones y OF a mano, repartir carga y rendimiento de cada equipo."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ... import configuracion
from ...servicios import carga as cg
from ..deps import UsuarioActual, ahora, get_sesion, requiere

router = APIRouter(tags=["carga de trabajo"])


def _no_existe(e: LookupError) -> HTTPException:
    return HTTPException(404, str(e))


class CambioOperacion(BaseModel):
    minutos: float | None = None
    maquina: str | None = None
    seccion: str | None = None
    tipo: str | None = None
    descripcion: str | None = None
    motivo: str | None = None


@router.patch("/operaciones/{op_id}")
def editar_operacion(op_id: int, datos: CambioOperacion, s: Session = Depends(get_sesion), u: UsuarioActual = Depends(requiere("modificar_plan"))) -> dict:
    try:
        return cg.editar_operacion(s, op_id, datos.model_dump(exclude_unset=True, exclude={"motivo"}), u.usuario, datos.motivo)
    except LookupError as e:
        raise _no_existe(e) from e


class NuevaOperacion(BaseModel):
    tipo: str
    minutos: float
    seccion: str | None = None
    maquina: str | None = None
    descripcion: str | None = None
    cantidad: float | None = None
    despues_de: int | None = None
    motivo: str | None = None


@router.post("/ofs/{of_id}/operaciones")
def anadir_operacion(of_id: int, datos: NuevaOperacion, s: Session = Depends(get_sesion), u: UsuarioActual = Depends(requiere("modificar_plan"))) -> dict:
    try:
        return cg.anadir_operacion(s, of_id, datos.model_dump(exclude={"motivo"}), u.usuario, datos.motivo)
    except LookupError as e:
        raise _no_existe(e) from e


@router.delete("/operaciones/{op_id}")
def quitar_operacion(op_id: int, motivo: str | None = None, s: Session = Depends(get_sesion), u: UsuarioActual = Depends(requiere("modificar_plan"))) -> dict:
    try:
        return cg.eliminar_operacion(s, op_id, u.usuario, motivo)
    except LookupError as e:
        raise _no_existe(e) from e


class NuevaOF(BaseModel):
    numero: str | None = None
    descripcion: str | None = None
    tanda_id: int | None = None
    aparato_id: int | None = None
    semana: str | None = None
    cantidad: float | None = None
    urgente: bool = False
    operaciones: list[NuevaOperacion]
    motivo: str | None = None


@router.post("/ofs")
def crear_of(datos: NuevaOF, s: Session = Depends(get_sesion), u: UsuarioActual = Depends(requiere("modificar_plan"))) -> dict:
    return cg.crear_of(s, datos.model_dump(), u.usuario)


@router.delete("/ofs/{of_id}")
def eliminar_of(of_id: int, motivo: str | None = None, s: Session = Depends(get_sesion), u: UsuarioActual = Depends(requiere("modificar_plan"))) -> dict:
    try:
        return cg.eliminar_of(s, of_id, u.usuario, motivo)
    except LookupError as e:
        raise _no_existe(e) from e


class MoverCarga(BaseModel):
    desde_maquina: str | None = None
    desde_seccion: str | None = None
    hacia_maquina: str | None = None
    hacia_seccion: str | None = None
    tipo: str | None = None
    tanda_id: int | None = None
    of_ids: list[int] | None = None
    fijar_maquina: bool | None = None
    motivo: str | None = None


@router.post("/carga/mover")
def mover(datos: MoverCarga, aplicar: bool = True, s: Session = Depends(get_sesion), u: UsuarioActual = Depends(requiere("planificar"))) -> dict:
    """Con aplicar=false solo dice cuánto se movería (vista previa)."""
    return cg.mover_carga(s, datos.model_dump(exclude_none=True), u.usuario, aplicar)


@router.get("/carga")
def carga(dias: int = 14, s: Session = Depends(get_sesion), _: UsuarioActual = Depends(requiere("ver"))) -> dict:
    return cg.resumen_carga(s, ahora(), dias)


class Rendimiento(BaseModel):
    seccion: str
    rendimiento: float
    motivo: str | None = None


@router.put("/carga/rendimiento")
def rendimiento(datos: Rendimiento, s: Session = Depends(get_sesion), u: UsuarioActual = Depends(requiere("planificar"))) -> dict:
    if not 20 <= datos.rendimiento <= 300:
        raise HTTPException(400, "El rendimiento va de 20 % a 300 %")
    valor = dict(configuracion.obtener(s, "rendimiento_secciones"))
    if datos.rendimiento == 100:
        valor.pop(datos.seccion, None)
    else:
        valor[datos.seccion] = datos.rendimiento
    configuracion.guardar(s, "rendimiento_secciones", valor, u.usuario, datos.motivo or f"Rendimiento de {datos.seccion} al {datos.rendimiento:g} %")
    return {"rendimiento_secciones": valor}
