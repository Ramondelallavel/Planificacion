"""Selección adaptativa del tamaño de bloque.

El tamaño inicial se estima con el número de páginas, el tamaño del fichero y una muestra
de las primeras páginas (texto e imágenes). Después se ajusta con el tiempo real medido por
página para que cada bloque tarde unos pocos segundos: así la barra de progreso avanza de
forma regular y la memoria por bloque queda acotada.
"""

from __future__ import annotations

from dataclasses import dataclass

import pymupdf

OBJETIVO_SEGUNDOS_BLOQUE = 4.0


@dataclass
class PlanBloques:
    tamano_inicial: int
    motivo: str


def estimar_tamano_bloque(
    doc: pymupdf.Document,
    tamano_bytes: int,
    minimo: int,
    maximo: int,
    memoria_mb: int,
    muestra: int = 3,
) -> PlanBloques:
    n = doc.page_count
    if n <= minimo:
        return PlanBloques(max(1, n), f"documento pequeño ({n} páginas): un único bloque")
    bytes_pagina = tamano_bytes / max(n, 1)
    chars = imagenes = 0
    k = min(muestra, n)
    for i in range(k):
        pg = doc.load_page(i)
        chars += len(pg.get_text("text"))
        imagenes += len(pg.get_images(full=False))
        del pg
    chars_pag = chars / k
    img_pag = imagenes / k
    # Estimación prudente de memoria de trabajo por página: estructura de spans (~40 B/carácter),
    # registros intermedios y buffers del PDF. Las páginas con muchas imágenes pesan más (posible OCR).
    mem_pag_mb = (chars_pag * 40 + bytes_pagina * 2) / 1e6 + img_pag * 0.5
    por_memoria = int(memoria_mb / max(mem_pag_mb, 0.05))
    tam = max(minimo, min(maximo, por_memoria))
    if n <= maximo and n <= por_memoria:
        tam = max(minimo, min(tam, (n + 1) // 2))  # al menos 2 bloques para reportar progreso
    motivo = (
        f"{n} páginas, {tamano_bytes / 1e6:.1f} MB (~{bytes_pagina / 1e3:.0f} kB/pág), "
        f"~{chars_pag:.0f} caracteres/pág, {img_pag:.1f} imágenes/pág → ~{mem_pag_mb:.2f} MB/pág; "
        f"límite de memoria por bloque {memoria_mb} MB → bloque de {tam} páginas"
    )
    return PlanBloques(tam, motivo)


def ajustar_tamano(actual: int, segundos_bloque: float, paginas_bloque: int, minimo: int, maximo: int) -> int:
    if paginas_bloque <= 0 or segundos_bloque <= 0:
        return actual
    por_pagina = segundos_bloque / paginas_bloque
    ideal = int(OBJETIVO_SEGUNDOS_BLOQUE / max(por_pagina, 1e-3))
    # suavizado: no más de x2 o /2 de un bloque al siguiente
    nuevo = max(actual // 2, min(actual * 2, ideal))
    return max(minimo, min(maximo, nuevo))
