"""Clasificación determinista de páginas por sus marcadores textuales y de maquetación.

Una página que no encaja en ningún formato conocido queda como DESCONOCIDA y genera una
incidencia de datos para revisión humana: nunca se adivina su tipo.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from ..modelos.enums import TipoPagina
from .extraccion import PaginaExtraida

_RE_CAB = re.compile(r"^S\d{1,2}-[A-Z]{1,4}-\d{4,6}$")


@dataclass(slots=True)
class Clasificacion:
    tipo: TipoPagina
    motivo: str


def clasificar(pagina: PaginaExtraida) -> Clasificacion:
    if not pagina.spans:
        return Clasificacion(TipoPagina.SIN_TEXTO, f"sin texto extraíble ({pagina.num_imagenes} imágenes)")
    textos = [s.texto for s in pagina.spans]
    conjunto = set(textos)
    unido = "\n".join(textos)

    if "LISTA DE MATERIALES" in conjunto:
        return Clasificacion(TipoPagina.LISTA_MATERIALES, "rótulo 'LISTA DE MATERIALES'")
    if "RELACIÓN DE BULTOS" in conjunto or "PACKING LIST" in conjunto:
        return Clasificacion(TipoPagina.PACKING_LIST, "rótulo 'RELACIÓN DE BULTOS / PACKING LIST'")
    if "Hoja de Fabricación" in conjunto and {"Pieza", "Destino"} <= conjunto:
        return Clasificacion(TipoPagina.HOJA_LCH, "rótulo 'Hoja de Fabricación' con tabla Pieza/Destino")
    if "TANDA" in unido and "GRUPO HF:" in unido:
        if any(_RE_CAB.match(t) for t in textos):
            return Clasificacion(TipoPagina.HOJA_CAB_PUERTAS, "cabecera 'Sxx-TIPO-control' de hoja CAB")
        return Clasificacion(TipoPagina.HOJA_GRUPO_HF, "cabecera TANDA / SECCIÓN / GRUPO HF")
    if "Hoja de Fabricación" in conjunto:
        return Clasificacion(TipoPagina.HOJA_LCH, "rótulo 'Hoja de Fabricación' (sin tabla en esta página)")
    return Clasificacion(TipoPagina.DESCONOCIDA, "no coincide con ningún formato conocido")
