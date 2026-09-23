"""Contexto documental ligero que se arrastra de página en página.

Solo guarda identificadores y posiciones de columnas (unos cientos de bytes), nunca
contenido de páginas anteriores. Es serializable para poder reanudar un trabajo
interrumpido a partir del último bloque persistido.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date


@dataclass
class ContextoDocumento:
    tanda_numero: str | None = None
    tanda_producto: str | None = None
    fecha_emision: str | None = None  # ISO
    # Hoja actual
    tipo_pagina: str | None = None
    seccion_codigo: str | None = None
    seccion_completa: str | None = None
    grupo_hf: str | None = None
    pagina_de: tuple[int, int] | None = None
    # OF y aparato activos (para continuaciones "Página 2 de 3")
    of_numero: str | None = None
    of_modo: str | None = None
    columnas: dict[str, tuple[float, float]] = field(default_factory=dict)
    zona_parametros_x: float | None = None
    numero_control: str | None = None
    tipo_aparato: str | None = None
    semana_codigo: str | None = None
    ultima_linea_idx: int | None = None  # índice dentro del bloque actual (no se persiste)
    # Lista de materiales (continúa entre páginas del mismo nº de control)
    bom_control: str | None = None
    bom_bulto: str | None = None
    bom_subbulto: str | None = None
    # Conjunto de OF ya vistas en este documento (para distinguir continuación de duplicado)
    ofs_vistas: dict[str, dict] = field(default_factory=dict)

    def anio_emision(self) -> int | None:
        if not self.fecha_emision:
            return None
        return date.fromisoformat(self.fecha_emision).year

    def a_dict(self) -> dict:
        d = asdict(self)
        d.pop("ultima_linea_idx", None)
        d["columnas"] = {k: list(v) for k, v in self.columnas.items()}
        d["pagina_de"] = list(self.pagina_de) if self.pagina_de else None
        return d

    @classmethod
    def desde_dict(cls, d: dict | None) -> ContextoDocumento:
        if not d:
            return cls()
        d = dict(d)
        d["columnas"] = {k: tuple(v) for k, v in (d.get("columnas") or {}).items()}
        d["pagina_de"] = tuple(d["pagina_de"]) if d.get("pagina_de") else None
        d.pop("ultima_linea_idx", None)
        return cls(**d)

    def nueva_hoja(self) -> None:
        """Al empezar una hoja distinta (no continuación) se olvida la OF/aparato activos."""
        self.of_numero = None
        self.of_modo = None
        self.numero_control = None
        self.tipo_aparato = None
        self.semana_codigo = None
