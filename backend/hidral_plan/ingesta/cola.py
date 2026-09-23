"""Trabajador de la cola de procesamiento documental.

Uso en producción (proceso separado, uno o varios):
    python -m hidral_plan.ingesta.cola

En PostgreSQL varios trabajadores pueden convivir gracias a FOR UPDATE SKIP LOCKED. Los
trabajos cuyo latido lleva más de LATIDO_MAX sin actualizarse se consideran abandonados
(el proceso murió) y se reanudan desde su último bloque persistido.
"""

from __future__ import annotations

import logging
import os
import socket
import threading
import time
from datetime import timedelta

from sqlalchemy import or_, select

from ..config import ajustes
from ..db import crear_tablas, es_postgres, sesion
from ..modelos import TrabajoProcesamiento
from ..modelos.comun import ahora
from ..modelos.enums import EstadoTrabajo
from .pipeline import procesar_trabajo

log = logging.getLogger(__name__)
LATIDO_MAX = timedelta(minutes=5)
INTENTOS_MAX = 3
_bloqueo_local = threading.Lock()


def reclamar_trabajo(nombre: str) -> int | None:
    with _bloqueo_local, sesion() as s:
        limite = ahora() - LATIDO_MAX
        q = (
            select(TrabajoProcesamiento)
            .where(
                or_(
                    TrabajoProcesamiento.estado == EstadoTrabajo.EN_COLA,
                    (TrabajoProcesamiento.estado == EstadoTrabajo.PROCESANDO) & (TrabajoProcesamiento.latido < limite),
                )
            )
            .order_by(TrabajoProcesamiento.id)
            .limit(1)
        )
        if es_postgres():
            q = q.with_for_update(skip_locked=True)
        t = s.scalar(q)
        if t is None:
            return None
        t.intentos += 1
        if t.intentos > INTENTOS_MAX:
            t.estado = EstadoTrabajo.ERROR
            t.mensaje_error = f"Abandonado tras {INTENTOS_MAX} intentos"
            return None
        t.estado = EstadoTrabajo.PROCESANDO
        t.trabajador = nombre
        t.latido = ahora()
        return t.id


def bucle(parar: threading.Event | None = None, nombre: str | None = None) -> None:
    nombre = nombre or f"{socket.gethostname()}:{os.getpid()}:{threading.get_ident()}"
    intervalo = ajustes().worker_intervalo_s
    log.info("Trabajador de ingesta %s iniciado", nombre)
    while not (parar and parar.is_set()):
        try:
            trabajo_id = reclamar_trabajo(nombre)
        except Exception:
            log.exception("Error reclamando trabajo")
            trabajo_id = None
        if trabajo_id is None:
            time.sleep(intervalo)
            continue
        procesar_trabajo(trabajo_id, nombre)


def iniciar_en_hilo() -> tuple[threading.Thread, threading.Event]:
    parar = threading.Event()
    hilo = threading.Thread(target=bucle, args=(parar,), name="hidral-ingesta", daemon=True)
    hilo.start()
    return hilo, parar


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    crear_tablas()
    bucle()
