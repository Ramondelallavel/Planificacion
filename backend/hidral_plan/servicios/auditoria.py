from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from ..modelos import Auditoria


def auditar(
    s: Session,
    usuario: str,
    accion: str,
    entidad_tipo: str | None = None,
    entidad_id: str | int | None = None,
    antes: Any = None,
    despues: Any = None,
    motivo: str | None = None,
    automatica: bool = False,
) -> None:
    s.add(
        Auditoria(
            usuario=usuario,
            accion=accion,
            entidad_tipo=entidad_tipo,
            entidad_id=None if entidad_id is None else str(entidad_id),
            antes=antes,
            despues=despues,
            motivo=motivo,
            automatica=automatica,
        )
    )
