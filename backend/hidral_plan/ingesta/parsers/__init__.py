from __future__ import annotations

from ...modelos.enums import Severidad, TipoPagina
from ..contexto import ContextoDocumento
from ..extraccion import PaginaExtraida
from ..registros import RegAviso, Registro
from .hoja_cab import parsear_hoja_cab
from .hoja_grupo_hf import parsear_hoja_grupo_hf
from .hoja_lch import parsear_hoja_lch
from .lista_materiales import parsear_lista_materiales
from .packing_list import parsear_packing_list

PARSERS = {
    TipoPagina.HOJA_GRUPO_HF: parsear_hoja_grupo_hf,
    TipoPagina.HOJA_CAB_PUERTAS: parsear_hoja_cab,
    TipoPagina.HOJA_LCH: parsear_hoja_lch,
    TipoPagina.LISTA_MATERIALES: parsear_lista_materiales,
    TipoPagina.PACKING_LIST: parsear_packing_list,
}


def parsear_pagina(tipo: TipoPagina, pagina: PaginaExtraida, ctx: ContextoDocumento) -> list[Registro]:
    parser = PARSERS.get(tipo)
    if parser is None:
        if tipo == TipoPagina.SIN_TEXTO:
            return [
                RegAviso(
                    "PAGINA_SIN_TEXTO",
                    Severidad.ADVERTENCIA,
                    f"Página sin texto extraíble ({pagina.num_imagenes} imagen/es). "
                    + ("; ".join(pagina.avisos) if pagina.avisos else "")
                    + " Revisar si contiene información de fabricación.",
                    pagina.numero,
                    entidad_tipo="PAGINA",
                    entidad_ref=str(pagina.numero),
                )
            ]
        return [
            RegAviso(
                "PAGINA_NO_CLASIFICADA",
                Severidad.ERROR,
                "Formato de página no reconocido: no se ha extraído ningún dato. REVISIÓN NECESARIA.",
                pagina.numero,
                texto_origen=pagina.texto[:1500],
                entidad_tipo="PAGINA",
                entidad_ref=str(pagina.numero),
            )
        ]
    return parser(pagina, ctx)
