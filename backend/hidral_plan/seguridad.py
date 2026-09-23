"""Autenticación (contraseñas PBKDF2 + token firmado HMAC) y permisos por rol.

Sin dependencias externas: hashlib/hmac de la biblioteca estándar.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import time

from .config import ajustes
from .modelos.enums import Rol

# Configurable para entornos sin OpenSSL (navegador), donde PBKDF2 se calcula en Python puro.
# El número de iteraciones queda guardado en cada hash, así que cambiarlo no invalida los existentes.
ITERACIONES = int(os.environ.get("HIDRAL_PBKDF2_ITERACIONES", "240000"))

# Permisos por rol (punto 41). La API comprueba el permiso en cada acción.
PERMISOS: dict[str, set[str]] = {
    Rol.ADMINISTRADOR: {"*"},
    Rol.PLANIFICADOR: {
        "ver",
        "importar",
        "planificar",
        "modificar_plan",
        "configurar",
        "recursos",
        "incidencias",
        "simular",
        "validar_datos",
        "aprobar_estimaciones",
        "fichar_supervisado",
    },
    Rol.JEFE_EQUIPO: {"ver", "planificar", "modificar_plan", "incidencias", "simular", "validar_datos", "fichar_supervisado", "importar"},
    Rol.SUPERVISOR: {"ver", "incidencias", "simular", "fichar_supervisado", "validar_datos"},
    Rol.OPERARIO: {"ver_propio", "fichar", "incidencias"},
    Rol.CONSULTA: {"ver"},
}


def tiene_permiso(rol: str, permiso: str) -> bool:
    p = PERMISOS.get(rol, set())
    return "*" in p or permiso in p or (permiso == "ver_propio" and "ver" in p)


def _pbkdf2_sha256(clave: bytes, sal: bytes, iteraciones: int) -> bytes:
    """PBKDF2-HMAC-SHA256 (RFC 8018). Usa hashlib si está disponible (compilado con OpenSSL);
    si no, una implementación con hmac equivalente para una clave de 32 bytes."""
    if hasattr(hashlib, "pbkdf2_hmac"):
        return hashlib.pbkdf2_hmac("sha256", clave, sal, iteraciones)
    base = hmac.new(clave, digestmod=hashlib.sha256)

    def prf(msg: bytes) -> bytes:
        h = base.copy()
        h.update(msg)
        return h.digest()

    u = prf(sal + b"\x00\x00\x00\x01")
    resultado = int.from_bytes(u, "big")
    for _ in range(iteraciones - 1):
        u = prf(u)
        resultado ^= int.from_bytes(u, "big")
    return resultado.to_bytes(32, "big")


def hash_clave(clave: str) -> str:
    sal = os.urandom(16)
    dk = _pbkdf2_sha256(clave.encode(), sal, ITERACIONES)
    return f"pbkdf2_sha256${ITERACIONES}${sal.hex()}${dk.hex()}"


def verificar_clave(clave: str, almacenado: str) -> bool:
    try:
        _, it, sal, dk = almacenado.split("$")
        calc = _pbkdf2_sha256(clave.encode(), bytes.fromhex(sal), int(it))
        return hmac.compare_digest(calc.hex(), dk)
    except ValueError:
        return False


def _b64(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def _unb64(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def emitir_token(usuario: str, rol: str, operario_id: int | None) -> str:
    carga = {"u": usuario, "r": rol, "o": operario_id, "exp": int(time.time()) + ajustes().token_horas * 3600}
    cuerpo = _b64(json.dumps(carga, separators=(",", ":")).encode())
    firma = _b64(hmac.new(ajustes().secreto.encode(), cuerpo.encode(), hashlib.sha256).digest())
    return f"{cuerpo}.{firma}"


def leer_token(token: str) -> dict | None:
    try:
        cuerpo, firma = token.split(".")
    except ValueError:
        return None
    esperada = _b64(hmac.new(ajustes().secreto.encode(), cuerpo.encode(), hashlib.sha256).digest())
    if not hmac.compare_digest(esperada, firma):
        return None
    datos = json.loads(_unb64(cuerpo))
    if datos.get("exp", 0) < time.time():
        return None
    return datos
