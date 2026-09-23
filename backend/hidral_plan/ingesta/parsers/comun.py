"""Cabecera común de las hojas de tanda y expresiones regulares compartidas."""

from __future__ import annotations

import re
from dataclasses import dataclass

from ...modelos.enums import Severidad
from ..contexto import ContextoDocumento
from ..extraccion import PaginaExtraida, Span
from ..normalizacion import fecha_desde_texto, semana_desde_corta, separar_seccion
from ..registros import RegAparato, RegAviso, RegTanda

RE_TANDA = re.compile(r"TANDA\s+(\d+)\s*:\s*(.*)")
RE_GRUPO_HF = re.compile(r"GRUPO HF:\s*(.+)")
RE_PAGINA_DE = re.compile(r"P[áa]gina\s+(\d+)\s+de\s+(\d+)")
RE_NUM_OF = re.compile(r"^\d{6,8}$")
# Código de artículo: numérico ("3001000/4"), de bulto ("B3421000/6"), documental ("IM-341en/12",
# "EE-311/21") o de consumible ("CO000004/B")
COD_ARTICULO = r"(?:B?\d{5,8}|[A-Z]{1,3}-\d{2,5}[a-z]{0,3}|[A-Z]{2}\d{5,7})/[0-9A-Z]+"
RE_ARTICULO = re.compile(rf"^(?P<cod>{COD_ARTICULO})\s*-\s*(?P<desc>.+)$")
RE_APARATO_FILA = re.compile(r"^S(?P<sem>\d{1,2})\s+(?P<tipo>[A-Z]{1,4})\s*-\s*(?P<ctrl>\d{4,6})(?:\s+(?P<resto>.+))?$")
RE_APARATO_TITULO = re.compile(r"^(?P<tipo>[A-Z]{1,4})-(?P<ctrl>\d{4,6})\s*-\s*(?P<desc>.+)$")
RE_PROGRAMA = re.compile(r"^(?P<prog>[A-Z]{2}\d{5,7}/[A-Z0-9]+)\s*-\s*(?P<desc>.+)$")
RE_PIEZA_ID = re.compile(r"^[A-Z]{1,4}-\d{4,6}-\d{3,5}$")
RE_CORTE = re.compile(r"^(?P<n>\d+)x(?P<l>\d+(?:[.,]\d+)?)$")
RE_CANTIDAD = re.compile(r"^\d+(?:[.,]\d+)?$")
MODOS = ("Conjunta-Pedido", "Serie-Conjunta", "Serie", "Conjunta", "Unitaria")


@dataclass
class Cabecera:
    tanda_numero: str | None = None
    tanda_producto: str | None = None
    seccion_completa: str | None = None
    seccion_codigo: str | None = None
    grupo_hf: str | None = None
    pagina_de: tuple[int, int] | None = None
    fecha_emision: str | None = None
    y_fin: float = 0.0
    texto: str = ""


def leer_cabecera(pagina: PaginaExtraida, y_max: float = 125.0) -> Cabecera:
    cab = Cabecera()
    partes = []
    spans = [s for s in pagina.spans if s.y0 <= y_max]
    for s in spans:
        t = s.texto
        if (m := RE_TANDA.search(t)) and cab.tanda_numero is None:
            cab.tanda_numero = m.group(1)
            cab.tanda_producto = m.group(2).strip() or None
            cab.y_fin = max(cab.y_fin, s.y1)
            partes.append(t)
        elif t.startswith("SECCIÓN:") or t.startswith("SECCION:"):
            cab.seccion_completa, cab.seccion_codigo = separar_seccion(t)
            cab.y_fin = max(cab.y_fin, s.y1)
            partes.append(t)
        elif m := RE_GRUPO_HF.search(t):
            cab.grupo_hf = m.group(1).strip()
            cab.y_fin = max(cab.y_fin, s.y1)
            partes.append(t)
        elif m := RE_PAGINA_DE.search(t):
            cab.pagina_de = (int(m.group(1)), int(m.group(2)))
            cab.y_fin = max(cab.y_fin, s.y1)
        elif t.startswith("F. Emisi"):
            # la fecha es el span inmediatamente a la derecha en la misma línea
            candidatos = [o for o in spans if abs(o.y0 - s.y0) < 2 and o.x0 >= s.x1 - 1]
            if candidatos:
                f = fecha_desde_texto(min(candidatos, key=lambda o: o.x0).texto)
                if f:
                    cab.fecha_emision = f.isoformat()
    cab.texto = " | ".join(partes)
    return cab


def registrar_cabecera(cab: Cabecera, pagina: PaginaExtraida, ctx: ContextoDocumento) -> list:
    regs: list = []
    if cab.tanda_numero:
        if ctx.tanda_numero and ctx.tanda_numero != cab.tanda_numero:
            regs.append(
                RegAviso(
                    "VARIAS_TANDAS",
                    Severidad.ADVERTENCIA,
                    f"La página pertenece a la TANDA {cab.tanda_numero} y el documento empezó con la TANDA {ctx.tanda_numero}.",
                    pagina.numero,
                    cab.texto,
                    "TANDA",
                    cab.tanda_numero,
                )
            )
        ctx.tanda_numero = cab.tanda_numero
        ctx.tanda_producto = cab.tanda_producto or ctx.tanda_producto
        regs.append(RegTanda(cab.tanda_numero, cab.tanda_producto, pagina.numero, cab.texto))
    if cab.fecha_emision:
        ctx.fecha_emision = cab.fecha_emision
    return regs


def es_continuacion(cab: Cabecera, ctx: ContextoDocumento) -> bool:
    return bool(
        cab.pagina_de and cab.pagina_de[0] > 1 and ctx.of_numero and ctx.seccion_completa == cab.seccion_completa and (ctx.grupo_hf == cab.grupo_hf or cab.grupo_hf is None)
    )


def semana_corta(ctx: ContextoDocumento, numero: int) -> tuple[str | None, str]:
    from datetime import date

    f = date.fromisoformat(ctx.fecha_emision) if ctx.fecha_emision else None
    return semana_desde_corta(numero, f)


def reg_aparato_desde_fila(tipo: str, control: str, semana_num: int, ctx: ContextoDocumento, pagina: int, texto: str) -> tuple[RegAparato, RegAviso | None]:
    codigo, motivo = semana_corta(ctx, semana_num)
    aviso = None
    if codigo is None:
        aviso = RegAviso(
            "SEMANA_NO_DERIVABLE",
            Severidad.ADVERTENCIA,
            f"S{semana_num:02d} sin año: {motivo}. Semana de fabricación: DATO NO DISPONIBLE.",
            pagina,
            texto,
            "APARATO",
            control,
        )
    reg = RegAparato(
        numero_control=control,
        pagina=pagina,
        texto_origen=texto,
        referencia=f"{tipo}-{control}",
        tipo=tipo,
        semana_codigo=codigo,
        semana_derivada=True,
    )
    ctx.numero_control = control
    ctx.tipo_aparato = tipo
    ctx.semana_codigo = codigo
    return reg, aviso


def span_derecha(spans: list[Span], ref: Span, tolerancia_y: float = 3.0) -> Span | None:
    candidatos = [s for s in spans if s is not ref and abs(s.y0 - ref.y0) <= tolerancia_y and s.x0 >= ref.x1 - 1]
    return min(candidatos, key=lambda s: s.x0) if candidatos else None
