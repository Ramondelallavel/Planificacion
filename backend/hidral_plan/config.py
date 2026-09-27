"""Configuración de la aplicación a partir de variables de entorno.

Nada de lo que aquí se define es un dato de fabricación: son parámetros técnicos
(conexión a BD, rutas, límites de procesamiento). Los datos de fábrica (máquinas,
turnos, tiempos estándar, pesos de prioridad) viven en la base de datos y se cargan
desde la configuración de fábrica (ver semilla.py).
"""

from __future__ import annotations

import os
import secrets
from dataclasses import dataclass, field
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent


def _secreto() -> str:
    """HIDRAL_SECRETO si está definido. Si no, uno aleatorio guardado junto a los datos (nunca un
    valor fijo conocido: con él cualquiera podría fabricar tokens de acceso)."""
    if os.environ.get("HIDRAL_SECRETO"):
        return os.environ["HIDRAL_SECRETO"]
    datos = Path(os.environ.get("HIDRAL_ALMACEN_DIR", str(BASE_DIR / "datos" / "almacen"))).parent
    fichero = datos / ".secreto"
    try:
        if fichero.exists() and len(fichero.read_text().strip()) >= 32:
            return fichero.read_text().strip()
        datos.mkdir(parents=True, exist_ok=True)
        valor = secrets.token_hex(32)
        fichero.write_text(valor)
        fichero.chmod(0o600)
        return valor
    except OSError:
        return secrets.token_hex(32)  # sin disco escribible: válido mientras dure el proceso


def _bool(nombre: str, defecto: bool) -> bool:
    valor = os.environ.get(nombre)
    if valor is None:
        return defecto
    return valor.strip().lower() in {"1", "true", "si", "sí", "yes", "on"}


@dataclass
class Ajustes:
    db_url: str = field(default_factory=lambda: os.environ.get("HIDRAL_DB_URL", f"sqlite:///{BASE_DIR / 'datos' / 'hidral.db'}"))
    almacen_dir: Path = field(default_factory=lambda: Path(os.environ.get("HIDRAL_ALMACEN_DIR", str(BASE_DIR / "datos" / "almacen"))))
    secreto: str = field(default_factory=_secreto)
    token_horas: int = field(default_factory=lambda: int(os.environ.get("HIDRAL_TOKEN_HORAS", "12")))
    # Procesamiento documental
    bloque_min_paginas: int = field(default_factory=lambda: int(os.environ.get("HIDRAL_BLOQUE_MIN", "5")))
    bloque_max_paginas: int = field(default_factory=lambda: int(os.environ.get("HIDRAL_BLOQUE_MAX", "50")))
    # Presupuesto de memoria orientativo (MB) que el pipeline intenta no superar por bloque.
    bloque_memoria_mb: int = field(default_factory=lambda: int(os.environ.get("HIDRAL_BLOQUE_MEMORIA_MB", "64")))
    # Tamaño máximo de un PDF subido y de un CSV importado
    max_pdf_mb: int = field(default_factory=lambda: int(os.environ.get("HIDRAL_MAX_PDF_MB", "300")))
    max_paginas: int = field(default_factory=lambda: int(os.environ.get("HIDRAL_MAX_PAGINAS", "5000")))
    max_csv_mb: int = field(default_factory=lambda: int(os.environ.get("HIDRAL_MAX_CSV_MB", "10")))
    # El texto de las páginas se guarda para auditoría; con esto, sin correos ni teléfonos
    ocultar_datos_personales: bool = field(default_factory=lambda: _bool("HIDRAL_OCULTAR_DATOS_PERSONALES", True))
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
