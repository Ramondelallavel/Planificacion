"""Aplicación FastAPI.

    uvicorn hidral_plan.api.app:app --reload
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from sqlalchemy.exc import DataError, IntegrityError

from ..config import ajustes
from ..db import crear_tablas
from ..planificacion.servicio import CambioRechazado, PlanBloqueado
from ..servicios.ejecucion import FichajeRechazado
from .rutas import auth, carga, dashboard, documentos, estructura, gestion, materiales, plan, planta, recursos

log = logging.getLogger(__name__)


@asynccontextmanager
async def ciclo_vida(app: FastAPI):
    crear_tablas()
    from ..db import sesion
    from ..servicios.privacidad import limpiar_datos_personales

    with sesion() as s:
        limpiar_datos_personales(s)
    parar = None
    if ajustes().worker_en_proceso:
        from ..ingesta.cola import iniciar_en_hilo

        _, parar = iniciar_en_hilo()
        log.info("Trabajador de ingesta arrancado en el propio proceso")
    yield
    if parar:
        parar.set()


class LimiteCuerpo:
    """Rechaza (413) una petición cuyo cuerpo supera el mayor fichero admitido sin llegar a leerla
    entera: nadie puede llenar la memoria o el disco del servidor con una subida enorme."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        limite = (max(ajustes().max_pdf_mb, ajustes().max_csv_mb) + 1) * 1024 * 1024
        texto = f"La petición supera el tamaño máximo admitido ({limite // (1024 * 1024)} MB)."
        longitud = dict(scope.get("headers") or []).get(b"content-length")
        if longitud is not None:
            n = int(longitud) if longitud.isdigit() else -1
            if n < 0 or n > limite:
                estado = 400 if n < 0 else 413
                return await JSONResponse({"detail": texto if n >= 0 else "Cabecera Content-Length no válida"}, estado)(scope, receive, send)
        recibido = 0

        async def recibir():
            # sin Content-Length (envío por trozos) se cuenta lo que va llegando
            nonlocal recibido
            m = await receive()
            if m["type"] == "http.request":
                recibido += len(m.get("body", b""))
                if recibido > limite:
                    raise HTTPException(413, texto)
            return m

        await self.app(scope, recibir, send)


def crear_app() -> FastAPI:
    app = FastAPI(
        title="HIDRAL — Planificación y control de fabricación",
        version="0.1.0",
        description="API del sistema de planificación APS/MES de HIDRAL. Todas las decisiones automáticas son explicables y auditadas.",
        lifespan=ciclo_vida,
    )
    app.add_middleware(LimiteCuerpo)
    app.add_middleware(CORSMiddleware, allow_origins=ajustes().cors_origenes, allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

    @app.middleware("http")
    async def cabeceras_seguridad(request: Request, call_next):
        r = await call_next(request)
        r.headers.setdefault("X-Content-Type-Options", "nosniff")
        r.headers.setdefault("Referrer-Policy", "same-origin")
        r.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
        if request.url.path.startswith("/api/"):
            r.headers.setdefault("Cache-Control", "no-store")
        return r

    @app.exception_handler(CambioRechazado)
    async def _cambio(_: Request, exc: CambioRechazado):
        return JSONResponse(status_code=409, content={"detail": "Cambio rechazado por restricciones duras", "errores": exc.errores})

    @app.exception_handler(PlanBloqueado)
    async def _bloqueado(_: Request, exc: PlanBloqueado):
        return JSONResponse(status_code=409, content={"detail": str(exc), "comprobaciones": exc.comprobaciones})

    @app.exception_handler(FichajeRechazado)
    async def _fichaje(_: Request, exc: FichajeRechazado):
        return JSONResponse(status_code=409, content={"detail": "No se puede fichar", "errores": exc.errores})

    @app.exception_handler(ValueError)
    async def _valor(_: Request, exc: ValueError):
        return JSONResponse(status_code=400, content={"detail": str(exc)})

    # Red de seguridad: lo que la base de datos rechaza llega como un mensaje, nunca como un 500
    @app.exception_handler(OverflowError)
    async def _desborde(_: Request, exc: OverflowError):
        return JSONResponse(status_code=400, content={"detail": "Número o fecha fuera de rango"})

    @app.exception_handler(IntegrityError)
    async def _integridad(request: Request, exc: IntegrityError):
        log.warning("Integridad rechazada en %s %s: %s", request.method, request.url.path, exc.orig)
        texto = str(exc.orig)
        if "uq_plan_oficial_activo" in texto or "plan.tipo" in texto:
            detalle = "Otra persona está generando el plan en este momento. Espera unos segundos y vuelve a intentarlo."
        elif "uq_fichaje_abierto_por_operario" in texto or "fichaje.operario_id" in texto:
            detalle = "Ese operario ya tiene un trabajo abierto: termínalo o páusalo primero."
        else:
            detalle = "No se puede guardar: hace referencia a algo que no existe (sección, turno, máquina…) o repite un dato que ya existe."
        return JSONResponse(status_code=409, content={"detail": detalle})

    @app.exception_handler(DataError)
    async def _dato(request: Request, exc: DataError):
        log.warning("Dato rechazado en %s %s: %s", request.method, request.url.path, exc.orig)
        return JSONResponse(status_code=400, content={"detail": "Algún valor no cabe en la base de datos: texto demasiado largo o número fuera de rango."})

    @app.exception_handler(Exception)
    async def _inesperado(request: Request, exc: Exception):
        log.exception("Error no controlado en %s %s", request.method, request.url.path)
        return JSONResponse(status_code=500, content={"detail": "Error interno. Ha quedado registrado; si se repite, avisa indicando qué estabas haciendo."})

    for r in (auth, documentos, estructura, plan, planta, recursos, dashboard, gestion, carga, materiales):
        app.include_router(r.router, prefix="/api")
    app.include_router(auth.usuarios, prefix="/api")

    @app.get("/api/salud")
    def salud() -> dict:
        return {"estado": "ok"}

    # Interfaz web compilada (frontend/dist) servida por la misma aplicación si existe
    dist = ajustes().frontend_dir
    if dist.exists():

        @app.get("/{ruta:path}", include_in_schema=False)
        def spa(ruta: str):
            if ruta == "api" or ruta.startswith("api/"):
                return JSONResponse(status_code=404, content={"detail": "Ruta de API inexistente"})
            f = dist / ruta
            if ruta and f.is_file() and dist in f.resolve().parents:
                return FileResponse(f)
            return FileResponse(dist / "index.html")

    return app


app = crear_app()
