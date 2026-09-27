"""Limpieza, una sola vez por base de datos, de correos y teléfonos en el texto guardado de los
documentos que se importaron antes de que existiera la ocultación automática."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import ajustes
from ..ingesta.normalizacion import ocultar_datos_personales
from ..modelos import Auditoria, IncidenciaDatos, LineaOF, Origen, PaginaDocumento
from .auditoria import auditar

ACCION = "OCULTAR_DATOS_PERSONALES"


def limpiar_datos_personales(s: Session) -> int:
    if not ajustes().ocultar_datos_personales or s.scalar(select(Auditoria.id).where(Auditoria.accion == ACCION).limit(1)):
        return 0
    n = 0
    for modelo, campo in ((PaginaDocumento, "texto"), (IncidenciaDatos, "texto_origen"), (Origen, "texto_origen"), (LineaOF, "texto_origen")):
        col = getattr(modelo, campo)
        for fila in s.scalars(select(modelo).where(col.is_not(None))):
            valor = getattr(fila, campo)
            nuevo = ocultar_datos_personales(valor)
            if nuevo != valor:
                setattr(fila, campo, nuevo)
                n += 1
    auditar(s, "sistema", ACCION, None, None, despues={"textos_limpiados": n}, automatica=True)
    return n
