"""Parser de la RELACIÓN DE BULTOS / PACKING LIST.

Solo se extraen los datos útiles para fabricación y expedición (nº control, cliente, su
referencia, producto y bultos con dimensiones y peso). Los datos de contacto personales del
pie (teléfonos, correos) no se copian a la base de datos estructurada.
"""

from __future__ import annotations

import re

from ...modelos.enums import Severidad
from ..contexto import ContextoDocumento
from ..extraccion import PaginaExtraida
from ..maquetacion import a_numero, agrupar_filas
from ..registros import RegAparato, RegAviso, RegBulto, Registro

RE_DIMS = re.compile(r"(\d+)\s*x\s*(\d+)\s*x\s*(\d+)")
RE_PESO = re.compile(r"(\d+(?:[.,]\d+)?)\s*kg")


def parsear_packing_list(pagina: PaginaExtraida, ctx: ContextoDocumento) -> list[Registro]:
    regs: list[Registro] = []
    filas = agrupar_filas(pagina.spans)
    control = su_ref = cliente = producto = None
    fila_cliente = None
    fila_producto = None
    for i, fila in enumerate(filas):
        t = fila.texto
        if "CONTROL" in t and control is None:
            nums = [s.texto for s in fila.spans if re.match(r"^\d{4,6}$", s.texto)]
            control = nums[-1] if nums else None
        elif t.startswith("SU REF") or "YOUR REF" in t:
            vals = [s.texto for s in fila.spans if s.x0 > 480 and not s.texto.startswith(("SU", "YOUR"))]
            su_ref = vals[0] if vals else None
        elif fila.spans and fila.spans[0].texto.startswith("CLIENTE") and fila_cliente is None and i + 1 < len(filas):
            fila_cliente = i + 1
        if "Dimensiones/Dimensions" in t:
            fila_producto = fila
            producto = fila.spans[0].texto if fila.spans and fila.spans[0].x0 < 100 else None
    if fila_cliente is not None:
        cand = [s for s in filas[fila_cliente].spans if s.x0 > 380]
        cliente = cand[0].texto if cand else None
    if control is None:
        regs.append(RegAviso("PACKING_SIN_CONTROL", Severidad.ERROR, "Packing list sin Nº CONTROL legible.", pagina.numero, pagina.texto[:500], "PAGINA", str(pagina.numero)))
        return regs
    regs.append(
        RegAparato(
            numero_control=control,
            pagina=pagina.numero,
            texto_origen=f"PACKING LIST Nº CONTROL {control}",
            producto=producto,
            cliente=cliente,
            su_referencia=su_ref,
            fuente_detalle="PACKING_LIST",
        )
    )
    if fila_producto is None:
        regs.append(RegAviso("PACKING_SIN_TABLA", Severidad.ADVERTENCIA, "No se encuentra la tabla de bultos.", pagina.numero, None, "APARATO", control))
        return regs
    for fila in filas:
        if fila.y <= fila_producto.y + 2:
            continue
        if fila.texto.startswith("El nº de bultos") or fila.texto.startswith("Nº DE BULTOS"):
            break
        numero = next((s for s in fila.spans if s.x0 < 65 and s.negrita and re.match(r"^\d{1,3}$", s.texto)), None)
        if numero is None:
            continue
        desc = " ".join(s.texto for s in fila.spans if 65 <= s.x0 < 400)
        der = " ".join(s.texto for s in fila.spans if s.x0 >= 400)
        dims = RE_DIMS.search(der)
        peso = RE_PESO.search(der)
        regs.append(
            RegBulto(
                numero_control=control,
                numero=numero.texto,
                pagina=pagina.numero,
                fuente_detalle="PACKING_LIST",
                texto_origen=fila.texto,
                descripcion=desc or None,
                largo_mm=float(dims.group(1)) if dims else None,
                ancho_mm=float(dims.group(2)) if dims else None,
                alto_mm=float(dims.group(3)) if dims else None,
                peso_kg=a_numero(peso.group(1)) if peso else None,
            )
        )
    return regs
