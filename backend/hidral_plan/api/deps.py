from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from datetime import datetime

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import ajustes
from ..db import fabrica_sesiones
from ..modelos import Usuario
from ..seguridad import leer_token, tiene_permiso


def get_sesion() -> Iterator[Session]:
    s = fabrica_sesiones()()
    try:
        yield s
        s.commit()
    except Exception:
        s.rollback()
        raise
    finally:
        s.close()


@dataclass
class UsuarioActual:
    usuario: str
    rol: str
    operario_id: int | None

    def puede(self, permiso: str) -> bool:
        return tiene_permiso(self.rol, permiso)


def usuario_actual(authorization: str | None = Header(default=None), s: Session = Depends(get_sesion)) -> UsuarioActual:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Falta el token de acceso")
    datos = leer_token(authorization.split(" ", 1)[1])
    if datos is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Token inválido o caducado")
    # el token no basta: un usuario dado de baja o con otro rol deja de valer al momento
    u = s.scalar(select(Usuario).where(Usuario.usuario == datos["u"]))
    if u is None or not u.activo:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Usuario inexistente o dado de baja")
    return UsuarioActual(u.usuario, u.rol, u.operario_id)


def requiere(permiso: str):
    def dep(u: UsuarioActual = Depends(usuario_actual)) -> UsuarioActual:
        if not u.puede(permiso):
            raise HTTPException(status.HTTP_403_FORBIDDEN, f"El rol {u.rol} no tiene permiso '{permiso}'")
        return u

    return dep


def requiere_alguno(*permisos: str):
    def dep(u: UsuarioActual = Depends(usuario_actual)) -> UsuarioActual:
        if not any(u.puede(p) for p in permisos):
            raise HTTPException(status.HTTP_403_FORBIDDEN, f"El rol {u.rol} no tiene permiso para esto")
        return u

    return dep


def ahora() -> datetime:
    fijo = ajustes().reloj_fijo
    if fijo:
        return datetime.fromisoformat(fijo)
    return datetime.now().replace(second=0, microsecond=0)
