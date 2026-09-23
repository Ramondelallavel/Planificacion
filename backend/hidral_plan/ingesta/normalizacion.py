"""Normalización determinista de valores del documento (semanas, secciones, artículos)."""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta

_RE_FECHA_CORTA = re.compile(r"(\d{2})/(\d{2})/(\d{2,4})")


def fecha_desde_texto(texto: str | None) -> date | None:
    if not texto:
        return None
    m = _RE_FECHA_CORTA.search(texto)
    if not m:
        return None
    d, mth, a = int(m.group(1)), int(m.group(2)), int(m.group(3))
    if a < 100:
        a += 2000
    try:
        return date(a, mth, d)
    except ValueError:
        return None


def semana_desde_corta(semana: int, fecha_emision: date | None) -> tuple[str | None, str]:
    """Convierte "S40" en "202640" usando el año de la fecha de emisión de la hoja.

    Regla documentada (no es una suposición libre): la semana de fabricación está en el
    futuro próximo respecto a la emisión. Si la semana indicada es más de 26 semanas
    anterior a la semana ISO de emisión, se entiende que pertenece al año siguiente
    (p.ej. emisión en diciembre y "S02"). Sin fecha de emisión → no se deriva.
    """
    if fecha_emision is None:
        return None, "sin fecha de emisión: no se puede derivar el año de la semana"
    anio, semana_emision, _ = fecha_emision.isocalendar()
    if semana < semana_emision - 26:
        anio += 1
        motivo = f"S{semana:02d} con emisión en semana {semana_emision}: se asigna al año siguiente {anio}"
    else:
        motivo = f"año {anio} tomado de la fecha de emisión {fecha_emision.isoformat()}"
    return f"{anio}{semana:02d}", motivo


def normalizar_semana_larga(texto: str) -> str | None:
    m = re.search(r"(20\d{2})(\d{2})", texto)
    if not m:
        return None
    semana = int(m.group(2))
    if not 1 <= semana <= 53:
        return None
    return f"{m.group(1)}{m.group(2)}"


def limites_semana(codigo: str) -> tuple[datetime, datetime]:
    """Lunes 00:00 y domingo 23:59:59 de la semana ISO AAAASS."""
    anio, semana = int(codigo[:4]), int(codigo[4:])
    lunes = date.fromisocalendar(anio, semana, 1)
    inicio = datetime.combine(lunes, datetime.min.time())
    return inicio, inicio + timedelta(days=7) - timedelta(seconds=1)


def semana_de_fecha(d: date | datetime) -> str:
    anio, semana, _ = d.isocalendar()
    return f"{anio}{semana:02d}"


def separar_seccion(texto: str) -> tuple[str | None, str | None]:
    """ "SC000003-MF" → ("SC000003-MF", "MF")."""
    m = re.search(r"(SC\d+)-([A-Z0-9]+)", texto)
    if not m:
        return None, None
    return f"{m.group(1)}-{m.group(2)}", m.group(2)


_RE_ART = re.compile(r"^(?P<base>B?\d{5,8})/(?P<rev>[0-9A-Z]+)$")


def partes_articulo(codigo: str) -> tuple[str, str | None]:
    m = _RE_ART.match(codigo)
    if not m:
        return codigo, None
    return m.group("base"), m.group("rev")
