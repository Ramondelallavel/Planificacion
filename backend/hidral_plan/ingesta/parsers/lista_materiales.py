"""Parser de la LISTA DE MATERIALES por aparato (bultos y componentes).

36747  LISTA DE MATERIALES  FFP 3193  Pág.1/4
Producto: ELEVADOR MONTACARGAS HO      Embalaje: NORMAL / PERSONALIZADO
Cliente: KONE ELEVADORES, S.A. (CENTRAL)
1 - B3001000/1 - GUIA-ACCIONAMIENTO          3365 x 510 x 545   208 kg
3001000/4 - CONJ. GUIAS-ACCIONAM. HO                1
4.1 - B3021100/1 - CAJA ACCESORIOS                  1
    2361021/1 - ANCLAJE TORNILLO ...                10   (sangrado → dentro del sub-bulto)
"""

from __future__ import annotations

import re

from ...modelos.enums import Severidad
from ..contexto import ContextoDocumento
from ..extraccion import PaginaExtraida
from ..maquetacion import a_numero, agrupar_filas
from ..registros import RegAparato, RegAviso, RegBulto, RegComponenteBulto, Registro
from .comun import COD_ARTICULO

RE_BULTO = re.compile(r"^(?P<num>\d+(?:\.\d+)*)\s*-\s*(?P<cod>B\d{5,8}/[0-9A-Z]+)\s*-\s*(?P<desc>.+)$")
RE_COMP = re.compile(rf"^(?P<cod>{COD_ARTICULO})\s*-\s*(?P<desc>.+?)(?:\s+--\s+(?P<par>.+))?$")
RE_DIMS = re.compile(r"(\d+)\s*x\s*(\d+)\s*x\s*(\d+)")
RE_PESO = re.compile(r"(\d+(?:[.,]\d+)?)\s*kg")
X_SANGRADO = 38.0


def _valor_derecha(fila, etiqueta: str) -> str | None:
    s = fila.buscar(etiqueta)
    if not s:
        return None
    derecha = [o for o in fila.spans if o.x0 > s.x1 - 1]
    return derecha[0].texto if derecha else None


def parsear_lista_materiales(pagina: PaginaExtraida, ctx: ContextoDocumento) -> list[Registro]:
    regs: list[Registro] = []
    # en las listas extracomunitarias la cantidad está 3 pt por debajo del texto del artículo
    filas = agrupar_filas(pagina.spans, tolerancia=4.0)
    control = None
    for s in pagina.spans:
        if s.y0 < 60 and s.negrita and s.tam >= 14 and re.match(r"^\d{4,6}$", s.texto):
            control = s.texto
    if control is None:
        regs.append(
            RegAviso("LISTA_SIN_CONTROL", Severidad.ERROR, "Lista de materiales sin número de control legible.", pagina.numero, pagina.texto[:500], "PAGINA", str(pagina.numero))
        )
        return regs
    if ctx.bom_control != control:
        ctx.bom_control, ctx.bom_bulto, ctx.bom_subbulto = control, None, None

    aparato = RegAparato(numero_control=control, pagina=pagina.numero, texto_origen=f"LISTA DE MATERIALES {control}", fuente_detalle="LISTA_MATERIALES")
    embalaje: list[str] = []
    en_tabla = False
    ultimo: RegComponenteBulto | RegBulto | None = None
    for fila in filas:
        textos = fila.textos()
        if not en_tabla:
            if "FFP" in textos:
                aparato.ffp = _valor_derecha(fila, "FFP")
            if "Producto:" in textos:
                aparato.producto = _valor_derecha(fila, "Producto:")
            if "Cliente:" in textos:
                aparato.cliente = _valor_derecha(fila, "Cliente:")
            emb = fila.buscar("Embalaje:")
            for s in fila.spans:
                if s.x0 > 455 and s.y0 > 80 and s.texto not in ("Embalaje:",) and not s.texto.startswith("Pág"):
                    if emb or embalaje:
                        embalaje.append(s.texto)
            if "Código" in textos and "Cantidad" in textos:
                en_tabla = True
            continue
        if all(s.cursiva and s.tam <= 7.5 for s in fila.spans):
            # traducción al inglés del elemento anterior (listas de pedidos extracomunitarios)
            if isinstance(ultimo, RegComponenteBulto):
                ultimo.traduccion = fila.texto.strip()
            continue
        txt_izq = " ".join(s.texto for s in fila.spans if s.x0 < 420)
        der = " ".join(s.texto for s in fila.spans if s.x0 >= 420)
        if m := RE_BULTO.match(txt_izq):
            num = m.group("num")
            dims = RE_DIMS.search(der)
            peso = RE_PESO.search(der)
            padre = None
            if "." in num:
                padre = num.rsplit(".", 1)[0]
                ctx.bom_subbulto = num
            else:
                ctx.bom_bulto, ctx.bom_subbulto = num, None
            ultimo = RegBulto(
                numero_control=control,
                numero=num,
                pagina=pagina.numero,
                fuente_detalle="LISTA_MATERIALES",
                texto_origen=fila.texto,
                codigo=m.group("cod"),
                descripcion=m.group("desc").strip(),
                largo_mm=float(dims.group(1)) if dims else None,
                ancho_mm=float(dims.group(2)) if dims else None,
                alto_mm=float(dims.group(3)) if dims else None,
                peso_kg=a_numero(peso.group(1)) if peso else None,
                padre=padre,
            )
            regs.append(ultimo)
            continue
        if m := RE_COMP.match(txt_izq):
            x0 = fila.spans[0].x0
            destino = ctx.bom_subbulto if (ctx.bom_subbulto and x0 > X_SANGRADO) else ctx.bom_bulto
            if destino is None:
                regs.append(
                    RegAviso("COMPONENTE_SIN_BULTO", Severidad.ERROR, "Componente de lista de materiales antes de cualquier bulto.", pagina.numero, fila.texto, "APARATO", control)
                )
                continue
            if x0 <= X_SANGRADO:
                ctx.bom_subbulto = None
            ultimo = RegComponenteBulto(
                numero_control=control,
                bulto_numero=destino,
                articulo_codigo=m.group("cod"),
                descripcion=m.group("desc").strip(),
                parametros=m.group("par"),
                cantidad=a_numero(der) if der else None,
                pagina=pagina.numero,
            )
            regs.append(ultimo)
            continue
        if fila.texto.strip():
            regs.append(RegAviso("FILA_NO_INTERPRETADA", Severidad.INFO, "Fila de lista de materiales no interpretada.", pagina.numero, fila.texto, "APARATO", control))
    if embalaje:
        aparato.embalaje = " / ".join(embalaje)
    regs.insert(0, aparato)
    return regs
