"""Edición «navegador»: la API completa ejecutándose dentro de Pyodide (Python en WebAssembly).

La interfaz no habla con un servidor: sus peticiones llegan a un Web Worker, que las entrega a
esta misma aplicación ASGI y le devuelve la respuesta. El código de negocio es exactamente el
del servidor. Lo único que cambia es el entorno:

  * no hay hilos: las funciones síncronas de FastAPI/Starlette se ejecutan en línea;
  * el procesamiento de PDF avanza bloque a bloque cuando el worker lo pide (`procesar_paso`),
    para poder informar del progreso entre bloques;
  * la base de datos es un fichero SQLite en el sistema de ficheros virtual (/datos), que el
    worker guarda en el navegador y del que puede exportar o restaurar una copia.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

# Carpeta de datos en el sistema de ficheros virtual (el worker la persiste en IndexedDB).
DATOS = Path(os.environ.get("HIDRAL_NAVEGADOR_DATOS", "/datos"))
RUTA_BD = DATOS / "hidral.db"

_app: Any = None


def _sin_hilos() -> None:
    """Starlette y FastAPI delegan todo el trabajo síncrono en `anyio.to_thread.run_sync`."""
    import anyio.to_thread

    async def run_sync(func, *args, abandon_on_cancel=False, cancellable=None, limiter=None):  # noqa: ARG001
        return func(*args)

    anyio.to_thread.run_sync = run_sync


def preparar(secreto: str, config_yaml: str | None = None, ahora_fijo: str | None = None) -> dict:
    """Configura el entorno, crea el esquema y, si la base está vacía, carga la configuración
    de fábrica indicada (marcada como EJEMPLO)."""
    global _app
    os.environ.update(
        {
            "HIDRAL_DB_URL": f"sqlite:///{RUTA_BD}",
            "HIDRAL_ALMACEN_DIR": str(DATOS / "almacen"),
            "HIDRAL_SECRETO": secreto,
            "HIDRAL_TOKEN_HORAS": "720",
            "HIDRAL_WORKER_EN_PROCESO": "0",
            "HIDRAL_OCR": "off",
            "HIDRAL_SQLITE_DIARIO": "DELETE",
            "HIDRAL_BLOQUE_MAX": "10",
            "HIDRAL_FRONTEND_DIR": "/sin-interfaz",
            # sin OpenSSL, PBKDF2 va en Python puro: menos iteraciones para no bloquear el login
            "HIDRAL_PBKDF2_ITERACIONES": "10000",
        }
    )
    if ahora_fijo:
        os.environ["HIDRAL_AHORA"] = ahora_fijo
    else:
        os.environ.pop("HIDRAL_AHORA", None)
    _sin_hilos()

    from sqlalchemy import select

    from .config import reiniciar_ajustes
    from .db import crear_tablas, reiniciar_motor, sesion
    from .modelos import Usuario

    reiniciar_ajustes()
    reiniciar_motor()
    crear_tablas()
    nueva = False
    with sesion() as s:
        if config_yaml and s.scalar(select(Usuario.id).limit(1)) is None:
            import yaml

            from .semilla import cargar_configuracion

            cargar_configuracion(s, yaml.safe_load(config_yaml), True)
            nueva = True

    from .api.app import crear_app

    _app = crear_app()
    return {"base_nueva": nueva}


async def peticion(metodo: str, ruta: str, cabeceras: Any = None, cuerpo: Any = None) -> dict:
    """Ejecuta una petición HTTP contra la aplicación y devuelve {estado, cabeceras, cuerpo}."""
    if hasattr(cabeceras, "to_py"):
        cabeceras = cabeceras.to_py()
    if hasattr(cuerpo, "to_bytes"):
        cuerpo = cuerpo.to_bytes()
    camino, _, consulta = ruta.partition("?")
    scope = {
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": "2.3"},
        "http_version": "1.1",
        "method": metodo.upper(),
        "scheme": "http",
        "path": camino,
        "raw_path": camino.encode(),
        "query_string": consulta.encode(),
        "root_path": "",
        "headers": [(k.lower().encode("latin-1"), str(v).encode("latin-1")) for k, v in (cabeceras or {}).items()],
        "client": ("navegador", 0),
        "server": ("hidral", 80),
    }
    pendiente = {"cuerpo": bytes(cuerpo or b""), "enviado": False}

    async def receive() -> dict:
        if not pendiente["enviado"]:
            pendiente["enviado"] = True
            return {"type": "http.request", "body": pendiente["cuerpo"], "more_body": False}
        return {"type": "http.disconnect"}

    respuesta: dict = {"estado": 500, "cabeceras": {}, "trozos": []}

    async def send(mensaje: dict) -> None:
        if mensaje["type"] == "http.response.start":
            respuesta["estado"] = mensaje["status"]
            respuesta["cabeceras"] = {k.decode("latin-1"): v.decode("latin-1") for k, v in mensaje.get("headers", [])}
        elif mensaje["type"] == "http.response.body":
            respuesta["trozos"].append(mensaje.get("body", b""))

    await _app(scope, receive, send)
    return {"estado": respuesta["estado"], "cabeceras": respuesta["cabeceras"], "cuerpo": b"".join(respuesta["trozos"])}


def procesar_paso() -> dict | None:
    """Avanza un bloque del primer documento en cola. None si no queda nada por procesar."""
    from sqlalchemy import select

    from .db import sesion
    from .ingesta.pipeline import procesar_trabajo
    from .modelos import TrabajoProcesamiento
    from .modelos.enums import EstadoTrabajo

    with sesion() as s:
        tid = s.scalar(
            select(TrabajoProcesamiento.id)
            .where(TrabajoProcesamiento.estado.in_([EstadoTrabajo.EN_COLA, EstadoTrabajo.PROCESANDO]))
            .order_by(TrabajoProcesamiento.id)
            .limit(1)
        )
    if tid is None:
        return None
    procesar_trabajo(tid, "navegador", max_bloques=1)
    with sesion() as s:
        t = s.get(TrabajoProcesamiento, tid)
        return {"trabajo_id": tid, "estado": t.estado, "paginas": t.paginas_procesadas, "total": t.paginas_totales, "fase": t.fase}


def cerrar_conexiones() -> None:
    """Cierra las conexiones para poder copiar o sustituir el fichero de la base de datos."""
    from .db import reiniciar_motor

    reiniciar_motor()


def reabrir() -> None:
    """Tras sustituir el fichero de la base de datos (restaurar una copia)."""
    from .db import crear_tablas, reiniciar_motor

    reiniciar_motor()
    crear_tablas()


def cargar_ejemplo(pdf: Any, nombre: str) -> dict:
    """Primera apertura: importa una tanda de ejemplo (datos ficticios) y genera un plan
    provisional, para que la aplicación arranque mostrando cómo trabaja."""
    import tempfile

    from .api.deps import ahora
    from .db import sesion
    from .ingesta.pipeline import procesar_sincrono
    from .planificacion import servicio as sv

    if hasattr(pdf, "to_bytes"):
        pdf = pdf.to_bytes()
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
        f.write(pdf)
        temporal = Path(f.name)
    r = procesar_sincrono(temporal, nombre, "sistema")
    with sesion() as s:
        plan = sv.generar_plan(s, "sistema", ahora(), nombre="Plan inicial (tanda de ejemplo)")
    return {"documento_id": r.documento_id, "plan_id": plan.get("plan_id")}
