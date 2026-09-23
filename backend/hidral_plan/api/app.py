"""Aplicación FastAPI.

    uvicorn hidral_plan.api.app:app --reload
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse

from ..config import ajustes
from ..db import crear_tablas
from ..planificacion.servicio import CambioRechazado, PlanBloqueado
from ..servicios.ejecucion import FichajeRechazado
from .rutas import auth, dashboard, documentos, estructura, gestion, plan, planta, recursos

log = logging.getLogger(__name__)


@asynccontextmanager
async def ciclo_vida(app: FastAPI):
    crear_tablas()
    parar = None
    if ajustes().worker_en_proceso:
        from ..ingesta.cola import iniciar_en_hilo

        _, parar = iniciar_en_hilo()
        log.info("Trabajador de ingesta arrancado en el propio proceso")
    yield
    if parar:
        parar.set()


def crear_app() -> FastAPI:
    app = FastAPI(
        title="HIDRAL — Planificación y control de fabricación",
        version="0.1.0",
        description="API del sistema de planificación APS/MES de HIDRAL. Todas las decisiones automáticas son explicables y auditadas.",
        lifespan=ciclo_vida,
    )
    app.add_middleware(CORSMiddleware, allow_origins=ajustes().cors_origenes, allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

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

    for r in (auth, documentos, estructura, plan, planta, recursos, dashboard, gestion):
        app.include_router(r.router, prefix="/api")

    @app.get("/api/salud")
    def salud() -> dict:
        return {"estado": "ok"}

    # Interfaz web compilada (frontend/dist) servida por la misma aplicación si existe
    dist = ajustes().frontend_dir
    if dist.exists():

        @app.get("/{ruta:path}", include_in_schema=False)
        def spa(ruta: str):
            f = dist / ruta
            if ruta and f.is_file() and dist in f.resolve().parents:
                return FileResponse(f)
            return FileResponse(dist / "index.html")

    return app


app = crear_app()
