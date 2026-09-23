from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from datetime import datetime

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy.orm import Session

from ..config import ajustes
from ..db import fabrica_sesiones
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


def usuario_actual(authorization: str | None = Header(default=None)) -> UsuarioActual:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Falta el token de acceso")
    datos = leer_token(authorization.split(" ", 1)[1])
    if datos is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Token inválido o caducado")
    return UsuarioActual(datos["u"], datos["r"], datos.get("o"))


def requiere(permiso: str):
    def dep(u: UsuarioActual = Depends(usuario_actual)) -> UsuarioActual:
        if not u.puede(permiso):
            raise HTTPException(status.HTTP_403_FORBIDDEN, f"El rol {u.rol} no tiene permiso '{permiso}'")
        return u

    return dep


def ahora() -> datetime:
    fijo = ajustes().reloj_fijo
    if fijo:
        return datetime.fromisoformat(fijo)
    return datetime.now().replace(second=0, microsecond=0)
