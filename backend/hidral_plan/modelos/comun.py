from __future__ import annotations

from datetime import datetime


def ahora() -> datetime:
    """Hora local de fábrica (naive). Todas las fechas del sistema están en hora local de planta."""
    return datetime.now().replace(microsecond=0)
