"""Configuración de la aplicación a partir de variables de entorno.

Nada de lo que aquí se define es un dato de fabricación: son parámetros técnicos
(conexión a BD, rutas, límites de procesamiento). Los datos de fábrica (máquinas,
turnos, tiempos estándar, pesos de prioridad) viven en la base de datos y se cargan
desde la configuración de fábrica (ver semilla.py).
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent


def _bool(nombre: str, defecto: bool) -> bool:
    valor = os.environ.get(nombre)
    if valor is None:
        return defecto
    return valor.strip().lower() in {"1", "true", "si", "sí", "yes", "on"}


@dataclass
class Ajustes:
    db_url: str = field(default_factory=lambda: os.environ.get("HIDRAL_DB_URL", f"sqlite:///{BASE_DIR / 'datos' / 'hidral.db'}"))
    almacen_dir: Path = field(default_factory=lambda: Path(os.environ.get("HIDRAL_ALMACEN_DIR", str(BASE_DIR / "datos" / "almacen"))))
    secreto: str = field(default_factory=lambda: os.environ.get("HIDRAL_SECRETO", "cambiar-en-produccion"))
    token_horas: int = field(default_factory=lambda: int(os.environ.get("HIDRAL_TOKEN_HORAS", "12")))
    # Procesamiento documental
    bloque_min_paginas: int = field(default_factory=lambda: int(os.environ.get("HIDRAL_BLOQUE_MIN", "5")))
    bloque_max_paginas: int = field(default_factory=lambda: int(os.environ.get("HIDRAL_BLOQUE_MAX", "50")))
    # Presupuesto de memoria orientativo (MB) que el pipeline intenta no superar por bloque.
    bloque_memoria_mb: int = field(default_factory=lambda: int(os.environ.get("HIDRAL_BLOQUE_MEMORIA_MB", "64")))
    ocr: str = field(default_factory=lambda: os.environ.get("HIDRAL_OCR", "auto"))  # auto | off
    # Trabajador de la cola: en desarrollo corre en un hilo del propio proceso de la API.
    worker_en_proceso: bool = field(default_factory=lambda: _bool("HIDRAL_WORKER_EN_PROCESO", True))
    worker_intervalo_s: float = field(default_factory=lambda: float(os.environ.get("HIDRAL_WORKER_INTERVALO", "1.0")))
    # Modo de diario de SQLite: WAL en disco normal; DELETE donde no hay memoria compartida (navegador).
    sqlite_diario: str = field(default_factory=lambda: os.environ.get("HIDRAL_SQLITE_DIARIO", "WAL").upper())
    # Reloj fijo opcional (ISO 8601) para demostraciones y pruebas reproducibles.
    reloj_fijo: str | None = field(default_factory=lambda: os.environ.get("HIDRAL_AHORA") or None)
    frontend_dir: Path = field(default_factory=lambda: Path(os.environ.get("HIDRAL_FRONTEND_DIR", str(BASE_DIR.parent / "frontend" / "dist"))))
    cors_origenes: list[str] = field(default_factory=lambda: os.environ.get("HIDRAL_CORS", "http://localhost:5173,http://127.0.0.1:5173").split(","))


_ajustes: Ajustes | None = None


def ajustes() -> Ajustes:
    global _ajustes
    if _ajustes is None:
        _ajustes = Ajustes()
    return _ajustes


def reiniciar_ajustes(nuevos: Ajustes | None = None) -> Ajustes:
    """Usado por los tests para aislar BD y almacén."""
    global _ajustes
    _ajustes = nuevos or Ajustes()
    return _ajustes
