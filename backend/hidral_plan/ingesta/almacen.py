"""Almacenamiento de ficheros originales separado de la BD (direccionado por contenido).

Implementación local en disco; la interfaz permite sustituirla por un almacén de objetos
(S3/MinIO) sin tocar el pipeline.
"""

from __future__ import annotations

import hashlib
import shutil
from pathlib import Path
from typing import BinaryIO

from ..config import ajustes

TAM_TROZO = 1024 * 1024


def hash_flujo(flujo: BinaryIO) -> tuple[str, int]:
    """SHA-256 leyendo por trozos de 1 MB (no carga el fichero completo en memoria)."""
    h = hashlib.sha256()
    total = 0
    while trozo := flujo.read(TAM_TROZO):
        h.update(trozo)
        total += len(trozo)
    return h.hexdigest(), total


def hash_fichero(ruta: Path) -> tuple[str, int]:
    with open(ruta, "rb") as f:
        return hash_flujo(f)


class AlmacenLocal:
    def __init__(self, raiz: Path | None = None) -> None:
        self.raiz = Path(raiz or ajustes().almacen_dir)
        self.raiz.mkdir(parents=True, exist_ok=True)

    def ruta_para(self, hash_hex: str, extension: str = ".pdf") -> Path:
        return self.raiz / hash_hex[:2] / f"{hash_hex}{extension}"

    def guardar_desde_temporal(self, temporal: Path, hash_hex: str) -> Path:
        destino = self.ruta_para(hash_hex)
        destino.parent.mkdir(parents=True, exist_ok=True)
        if not destino.exists():
            shutil.move(str(temporal), destino)
        else:
            temporal.unlink(missing_ok=True)
        return destino

    def abrir(self, ruta: str | Path) -> Path:
        p = Path(ruta)
        if not p.is_absolute():
            p = self.raiz / p
        if not p.exists():
            raise FileNotFoundError(p)
        return p
