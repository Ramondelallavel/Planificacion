"""Utilidades de maquetación: agrupar spans en filas y localizar columnas por cabecera."""

from __future__ import annotations

import re
from dataclasses import dataclass

from .extraccion import Span


@dataclass(slots=True)
class Fila:
    y: float
    spans: list[Span]

    @property
    def texto(self) -> str:
        return " ".join(s.texto for s in self.spans)

    def textos(self) -> list[str]:
        return [s.texto for s in self.spans]

    def buscar(self, texto: str) -> Span | None:
        for s in self.spans:
            if s.texto == texto:
                return s
        return None

    def empieza(self, prefijo: str) -> Span | None:
        for s in self.spans:
            if s.texto.startswith(prefijo):
                return s
        return None

    def en_rango(self, x_min: float, x_max: float) -> list[Span]:
        return [s for s in self.spans if x_min <= s.x0 < x_max]


def agrupar_filas(spans: list[Span], tolerancia: float = 3.0) -> list[Fila]:
    """Agrupa por proximidad vertical del borde superior (los textos de una misma fila
    de tabla pueden variar ±1 pt según el tamaño de letra)."""
    filas: list[Fila] = []
    for s in sorted(spans, key=lambda s: (s.y0, s.x0)):
        if filas and abs(s.y0 - filas[-1].y) <= tolerancia:
            filas[-1].spans.append(s)
        else:
            filas.append(Fila(s.y0, [s]))
    for f in filas:
        f.spans.sort(key=lambda s: s.x0)
    return filas


def columna_mas_cercana(span: Span, columnas: dict[str, tuple[float, float]], margen: float = 30.0) -> str | None:
    """Devuelve el nombre de la columna cuyo intervalo [x0, x1] de cabecera solapa o está
    más próximo al span. Tiene en cuenta valores alineados a derecha o izquierda."""
    mejor, dist_mejor = None, None
    for nombre, (c0, c1) in columnas.items():
        if span.x1 >= c0 - 2 and span.x0 <= c1 + 2:
            dist = abs(span.xc - (c0 + c1) / 2) * 0.1  # solape: preferente
        else:
            dist = min(abs(span.x0 - c1), abs(span.x1 - c0))
            if dist > margen:
                continue
        if dist_mejor is None or dist < dist_mejor:
            mejor, dist_mejor = nombre, dist
    return mejor


_RE_NUM = re.compile(r"^-?\d{1,3}(?:\.\d{3})*(?:,\d+)?$|^-?\d+(?:[.,]\d+)?$")


def a_numero(texto: str | None) -> float | None:
    """Convierte "1,5" / "1.284" / "2084,8" a número. Devuelve None si no es un número limpio.
    Nunca "adivina": un texto ambiguo devuelve None."""
    if texto is None:
        return None
    t = texto.strip().replace(" ", "")
    if not t or not _RE_NUM.match(t):
        return None
    if "," in t:
        t = t.replace(".", "").replace(",", ".")
    elif re.match(r"^-?\d{1,3}(\.\d{3})+$", t):
        # "1.284" en una hoja española es un millar; lo tratamos como tal solo si el patrón es inequívoco
        t = t.replace(".", "")
    try:
        return float(t)
    except ValueError:
        return None


_RE_PARAM = re.compile(r"([A-Za-z][A-Za-z0-9_]*)=([^\s=]*)")


def parametros_a_dict(texto: str | None) -> dict[str, str]:
    """ "R=2670 F=230 OpcGalvanizado=falso Color=" → {"R": "2670", ...}. Valores vacíos se conservan."""
    if not texto:
        return {}
    return {m.group(1): m.group(2) for m in _RE_PARAM.finditer(texto)}
