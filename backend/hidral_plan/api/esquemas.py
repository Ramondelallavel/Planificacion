"""Base de los modelos de entrada de la API: lo que ninguna ruta debe aceptar nunca.

- NaN e infinito (rompen cálculos y el motor al planificar).
- Números fuera del rango de la base de datos (identificadores de 20 cifras, 1e308 minutos…).
- Caracteres nulos (PostgreSQL no los admite en un texto).
- Textos desmesurados (cada columna tiene su tamaño; esto corta lo absurdo antes de llegar).
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, model_validator

ENTERO_MAX = 2**31 - 1  # columnas INTEGER de PostgreSQL
REAL_MAX = 1e9  # ningún dato de fabricación (minutos, cantidades, horas) se acerca a esto
TEXTO_MAX = 4000


def _revisar(valor: Any, campo: str) -> None:
    if isinstance(valor, bool) or valor is None:
        return
    if isinstance(valor, int):
        if not -ENTERO_MAX <= valor <= ENTERO_MAX:
            raise ValueError(f"{campo}: número fuera de rango")
    elif isinstance(valor, float):
        if not -REAL_MAX <= valor <= REAL_MAX:
            raise ValueError(f"{campo}: número fuera de rango")
    elif isinstance(valor, str):
        if "\x00" in valor:
            raise ValueError(f"{campo}: contiene caracteres no válidos")
        if len(valor) > TEXTO_MAX:
            raise ValueError(f"{campo}: texto demasiado largo (máximo {TEXTO_MAX} caracteres)")
    elif isinstance(valor, list | tuple | set):
        if len(valor) > 5000:
            raise ValueError(f"{campo}: demasiados elementos")
        for x in valor:
            _revisar(x, campo)
    elif isinstance(valor, dict):
        for k, x in valor.items():
            _revisar(k, campo)
            _revisar(x, f"{campo}.{k}")


class Entrada(BaseModel):
    model_config = ConfigDict(allow_inf_nan=False)

    @model_validator(mode="after")
    def _sin_valores_imposibles(self):
        for campo, valor in self:
            _revisar(valor, campo)
        return self
