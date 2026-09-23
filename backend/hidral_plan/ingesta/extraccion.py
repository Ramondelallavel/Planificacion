"""Extracción de una página: texto con posición y estilo (spans). OCR solo si no hay texto.

Se trabaja página a página sobre un documento abierto de forma perezosa (PyMuPDF solo
carga la página solicitada). Nada del documento completo se mantiene en memoria.
"""

from __future__ import annotations

import logging
import shutil
from dataclasses import dataclass, field

import pymupdf

log = logging.getLogger(__name__)

_FLAGS_TEXTO = pymupdf.TEXTFLAGS_DICT & ~pymupdf.TEXT_PRESERVE_IMAGES


@dataclass(slots=True)
class Span:
    x0: float
    y0: float
    x1: float
    y1: float
    texto: str
    fuente: str
    tam: float
    negrita: bool
    cursiva: bool

    @property
    def xc(self) -> float:
        return (self.x0 + self.x1) / 2

    @property
    def yc(self) -> float:
        return (self.y0 + self.y1) / 2


@dataclass(slots=True)
class PaginaExtraida:
    numero: int  # 1-based
    spans: list[Span]
    ancho: float
    alto: float
    metodo: str  # TEXTO | OCR | NINGUNO
    num_imagenes: int = 0
    avisos: list[str] = field(default_factory=list)

    @property
    def texto(self) -> str:
        return "\n".join(s.texto for s in self.spans)

    @property
    def num_caracteres(self) -> int:
        return sum(len(s.texto) for s in self.spans)


def _es_negrita(fuente: str, flags: int) -> bool:
    return "bold" in fuente.lower() or bool(flags & 16)


def _es_cursiva(fuente: str, flags: int) -> bool:
    f = fuente.lower()
    return "italic" in f or "oblique" in f or bool(flags & 2)


def ocr_disponible() -> bool:
    try:
        import pytesseract  # noqa: F401
    except ImportError:
        return False
    return shutil.which("tesseract") is not None


def _spans_ocr(pagina: pymupdf.Page) -> list[Span]:
    """OCR de una página renderizada (solo cuando no hay capa de texto)."""
    import pytesseract
    from PIL import Image

    zoom = 200 / 72
    pix = pagina.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom), colorspace=pymupdf.csGRAY)
    img = Image.frombytes("L", (pix.width, pix.height), pix.samples)
    del pix
    datos = pytesseract.image_to_data(img, lang="spa+eng", output_type=pytesseract.Output.DICT)
    spans: list[Span] = []
    for i, txt in enumerate(datos["text"]):
        if not txt or not txt.strip() or float(datos["conf"][i]) < 40:
            continue
        x, y, w, h = (datos[k][i] / zoom for k in ("left", "top", "width", "height"))
        spans.append(Span(x, y, x + w, y + h, txt.strip(), "OCR", h, False, False))
    return spans


def extraer_pagina(doc: pymupdf.Document, indice: int, modo_ocr: str = "auto") -> PaginaExtraida:
    pagina = doc.load_page(indice)
    try:
        datos = pagina.get_text("dict", flags=_FLAGS_TEXTO)
        spans: list[Span] = []
        for bloque in datos.get("blocks", []):
            for linea in bloque.get("lines", []):
                for s in linea.get("spans", []):
                    texto = s.get("text", "")
                    if not texto.strip():
                        continue
                    x0, y0, x1, y1 = s["bbox"]
                    fuente = s.get("font", "")
                    flags = int(s.get("flags", 0))
                    spans.append(
                        Span(
                            round(x0, 1),
                            round(y0, 1),
                            round(x1, 1),
                            round(y1, 1),
                            " ".join(texto.split()),
                            fuente,
                            round(float(s.get("size", 0)), 1),
                            _es_negrita(fuente, flags),
                            _es_cursiva(fuente, flags),
                        )
                    )
        num_imagenes = len(pagina.get_images(full=False))
        resultado = PaginaExtraida(
            numero=indice + 1,
            spans=spans,
            ancho=pagina.rect.width,
            alto=pagina.rect.height,
            metodo="TEXTO" if spans else "NINGUNO",
            num_imagenes=num_imagenes,
        )
        if not spans:
            if modo_ocr != "off" and ocr_disponible():
                try:
                    resultado.spans = _spans_ocr(pagina)
                    resultado.metodo = "OCR" if resultado.spans else "NINGUNO"
                    if not resultado.spans:
                        resultado.avisos.append("OCR ejecutado sin texto reconocible")
                except Exception as exc:  # el OCR nunca debe tumbar la ingesta
                    log.warning("OCR falló en página %s: %s", indice + 1, exc)
                    resultado.avisos.append(f"OCR falló: {exc}")
            else:
                resultado.avisos.append("Página sin capa de texto y OCR no disponible en este servidor")
        return resultado
    finally:
        del pagina
