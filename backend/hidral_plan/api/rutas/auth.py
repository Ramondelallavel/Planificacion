from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from ...modelos import Operario, Usuario
from ...seguridad import PERMISOS, emitir_token, verificar_clave
from ...servicios.auditoria import auditar
from ..deps import UsuarioActual, get_sesion, usuario_actual

router = APIRouter(prefix="/auth", tags=["autenticación"])


class Login(BaseModel):
    usuario: str
    clave: str


@router.post("/login")
def login(datos: Login, s: Session = Depends(get_sesion)) -> dict:
    u = s.scalar(select(Usuario).where(Usuario.usuario == datos.usuario, Usuario.activo.is_(True)))
    if u is None or not verificar_clave(datos.clave, u.hash_clave):
        auditar(s, datos.usuario, "LOGIN_FALLIDO")
        s.commit()
        raise HTTPException(401, "Usuario o contraseña incorrectos")
    auditar(s, u.usuario, "LOGIN")
    op = s.get(Operario, u.operario_id) if u.operario_id else None
    return {
        "token": emitir_token(u.usuario, u.rol, u.operario_id),
        "usuario": u.usuario,
        "nombre": u.nombre,
        "rol": u.rol,
        "operario_id": u.operario_id,
        "operario": op.nombre if op else None,
        "permisos": sorted(PERMISOS.get(u.rol, set())),
    }


@router.get("/yo")
def yo(u: UsuarioActual = Depends(usuario_actual)) -> dict:
    return {"usuario": u.usuario, "rol": u.rol, "operario_id": u.operario_id, "permisos": sorted(PERMISOS.get(u.rol, set()))}
