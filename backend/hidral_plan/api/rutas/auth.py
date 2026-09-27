from __future__ import annotations

from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ...modelos import Auditoria, Operario, Usuario
from ...modelos.comun import ahora as reloj
from ...seguridad import PERMISOS, emitir_token, hash_clave, verificar_clave
from ...servicios.auditoria import auditar
from ..deps import UsuarioActual, get_sesion, requiere, usuario_actual

router = APIRouter(prefix="/auth", tags=["autenticación"])


class Login(BaseModel):
    usuario: str
    clave: str


INTENTOS_MAX = 5
VENTANA_MIN = 15


def _fallos_recientes(s: Session, usuario: str) -> int:
    """Intentos fallidos en los últimos minutos, contados desde el último acceso correcto."""
    desde = reloj() - timedelta(minutes=VENTANA_MIN)
    ultimo_ok = s.scalar(select(func.max(Auditoria.fecha)).where(Auditoria.usuario == usuario, Auditoria.accion == "LOGIN"))
    if ultimo_ok and ultimo_ok > desde:
        desde = ultimo_ok
    return s.scalar(select(func.count(Auditoria.id)).where(Auditoria.usuario == usuario, Auditoria.accion == "LOGIN_FALLIDO", Auditoria.fecha > desde)) or 0


@router.post("/login")
def login(datos: Login, s: Session = Depends(get_sesion)) -> dict:
    usuario = datos.usuario.strip()[:80]
    if _fallos_recientes(s, usuario) >= INTENTOS_MAX:
        raise HTTPException(429, f"Demasiados intentos fallidos. Espera {VENTANA_MIN} minutos o pide a un administrador que revise la cuenta.")
    u = s.scalar(select(Usuario).where(Usuario.usuario == usuario, Usuario.activo.is_(True)))
    if u is None or not verificar_clave(datos.clave, u.hash_clave):
        auditar(s, usuario, "LOGIN_FALLIDO")
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


class CambioClave(BaseModel):
    actual: str
    nueva: str


def validar_clave(clave: str) -> None:
    if len(clave) < 8:
        raise HTTPException(400, "La contraseña necesita al menos 8 caracteres")


@router.post("/clave")
def cambiar_clave(datos: CambioClave, s: Session = Depends(get_sesion), yo_: UsuarioActual = Depends(usuario_actual)) -> dict:
    u = s.scalar(select(Usuario).where(Usuario.usuario == yo_.usuario))
    if u is None or not verificar_clave(datos.actual, u.hash_clave):
        raise HTTPException(400, "La contraseña actual no es correcta")
    validar_clave(datos.nueva)
    u.hash_clave = hash_clave(datos.nueva)
    auditar(s, u.usuario, "CAMBIO_CLAVE", "USUARIO", u.usuario)
    return {"usuario": u.usuario}


# ------------------------------------------------------------------ gestión de usuarios (administrador)
def _json(u: Usuario) -> dict:
    return {"usuario": u.usuario, "nombre": u.nombre, "rol": u.rol, "activo": u.activo, "operario_id": u.operario_id, "creado": u.creado.isoformat() if u.creado else None}


usuarios = APIRouter(prefix="/usuarios", tags=["usuarios"])


@usuarios.get("")
def listar_usuarios(s: Session = Depends(get_sesion), _: UsuarioActual = Depends(requiere("usuarios"))) -> list[dict]:
    return [_json(u) for u in s.scalars(select(Usuario).order_by(Usuario.usuario))]


class UsuarioIn(BaseModel):
    usuario: str | None = None
    nombre: str | None = None
    rol: str | None = None
    clave: str | None = None
    activo: bool | None = None
    operario_id: int | None = None


def _validar_rol_y_operario(s: Session, datos: UsuarioIn) -> None:
    if datos.rol is not None and datos.rol not in PERMISOS:
        raise HTTPException(400, f"Rol desconocido: {datos.rol}. Roles: {', '.join(PERMISOS)}")
    if datos.operario_id is not None and s.get(Operario, datos.operario_id) is None:
        raise HTTPException(400, "El operario indicado no existe")


@usuarios.post("")
def crear_usuario(datos: UsuarioIn, s: Session = Depends(get_sesion), yo_: UsuarioActual = Depends(requiere("usuarios"))) -> dict:
    nombre_usuario = (datos.usuario or "").strip().lower()
    if not nombre_usuario or not datos.nombre or not datos.rol or not datos.clave:
        raise HTTPException(400, "Usuario, nombre, rol y contraseña son obligatorios")
    if s.scalar(select(Usuario).where(Usuario.usuario == nombre_usuario)):
        raise HTTPException(409, "Ya existe ese usuario")
    _validar_rol_y_operario(s, datos)
    validar_clave(datos.clave)
    u = Usuario(usuario=nombre_usuario, nombre=datos.nombre, rol=datos.rol, hash_clave=hash_clave(datos.clave), activo=True, operario_id=datos.operario_id)
    s.add(u)
    s.flush()
    auditar(s, yo_.usuario, "CREAR_USUARIO", "USUARIO", u.usuario, despues={"rol": u.rol, "operario_id": u.operario_id})
    return _json(u)


@usuarios.patch("/{usuario}")
def cambiar_usuario(usuario: str, datos: UsuarioIn, s: Session = Depends(get_sesion), yo_: UsuarioActual = Depends(requiere("usuarios"))) -> dict:
    u = s.scalar(select(Usuario).where(Usuario.usuario == usuario))
    if u is None:
        raise HTTPException(404, "Usuario inexistente")
    _validar_rol_y_operario(s, datos)
    antes = _json(u)
    quita_admin = u.rol == "ADMINISTRADOR" and ((datos.rol is not None and datos.rol != "ADMINISTRADOR") or datos.activo is False)
    if quita_admin and not s.scalar(select(func.count(Usuario.id)).where(Usuario.rol == "ADMINISTRADOR", Usuario.activo.is_(True), Usuario.id != u.id)):
        raise HTTPException(409, "Es el último administrador activo: no se puede quitar")
    if u.usuario == yo_.usuario and datos.activo is False:
        raise HTTPException(409, "No puedes darte de baja a ti mismo")
    campos = datos.model_dump(exclude_unset=True, exclude={"usuario", "clave"})
    for k, v in campos.items():
        setattr(u, k, v)
    if datos.clave:
        validar_clave(datos.clave)
        u.hash_clave = hash_clave(datos.clave)
    auditar(s, yo_.usuario, "CAMBIO_USUARIO", "USUARIO", u.usuario, antes=antes, despues={**_json(u), "clave_cambiada": bool(datos.clave)})
    return _json(u)
