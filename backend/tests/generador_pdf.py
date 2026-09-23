"""Generador de PDF sintéticos con la maquetación de las hojas HIDRAL.

Sirve para los casos de prueba que el PDF de ejemplo no cubre (1, 2 y 4 aparatos, 600
páginas, dos tandas, datos ambiguos, nuevas versiones...). Reproduce las posiciones de
columna y los estilos (negrita / cursiva) que usan los parsers, NO copia contenido real.

Cadena de fabricación generada por aparato (todas las dependencias salen de las columnas
Sección/Orden y Destino, como en el documento real):

    LCH corte ──(Pleg.)──> LCH plegado (OF sin hoja) ──> EH soldadura
    COR LaserTub (programa PL...) ─────────────────────> EH soldadura
    EH soldadura ──> TPPINO pintura ──> MF montaje ──> MF embalaje (bulto)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

import pymupdf

N, B, I = "helv", "hebo", "heit"  # Helvetica, Helvetica-Bold, Helvetica-Oblique


@dataclass
class Aparato:
    control: str
    tipo: str = "EH"
    semana: int = 40
    ofs_relleno: int = 0  # OF adicionales de MF para engordar el documento
    bultos: int = 3


@dataclass
class OpcionesTanda:
    tanda: str = "9001"
    producto: str = "EH/DC-5000 | HO"
    emision: date = date(2026, 9, 15)
    aparatos: list[Aparato] = field(default_factory=lambda: [Aparato("40001")])
    base_of: int = 800000
    incluir_lch: bool = True
    incluir_cor: bool = True
    incluir_bom: bool = True
    incluir_packing: bool = True
    # variantes para casos de prueba
    fila_sin_cantidad: bool = False
    control_ambiguo: bool = False
    seccion_desconocida: bool = False
    of_duplicada: bool = False
    ciclo: bool = False
    omitir_embalaje_de: str | None = None  # nº control cuyo embalaje se omite (nueva versión)
    cantidad_montaje: int = 1


def _t(pg: pymupdf.Page, x: float, y: float, texto: str, f: str = N, tam: float = 8.0) -> None:
    pg.insert_text((x, y), texto, fontname=f, fontsize=tam)


def _cabecera_hf(pg, o: OpcionesTanda, seccion: str, grupo: str, pagina_de: tuple[int, int] = (1, 1)) -> None:
    _t(pg, 209, 49, f"TANDA {o.tanda}: {o.producto}", N, 13)
    _t(pg, 427, 49, "F. Impresión:", N, 9)
    _t(pg, 481, 49, o.emision.strftime("%d/%m/%y"), N, 9)
    _t(pg, 209, 63, f"SECCIÓN: {seccion}", B, 13)
    _t(pg, 435, 62, "F. Emisión:", N, 9)
    _t(pg, 481, 62, o.emision.strftime("%d/%m/%y"), N, 9)
    _t(pg, 460, 75, f"Página {pagina_de[0]} de {pagina_de[1]}", N, 9)
    _t(pg, 209, 76, f"GRUPO HF: {grupo}", N, 9)


def _orden(pg, y: float, numero: str, titulo: str, modo: str = "Conjunta-Pedido") -> float:
    _t(pg, 29, y, "ORDEN", B, 12)
    _t(pg, 76, y, numero, B, 12)
    _t(pg, 140, y, titulo, B, 10)
    _t(pg, 450, y, modo, N, 10)
    y += 14
    _t(pg, 387, y, "Cantidad", "hebi", 10)
    _t(pg, 476, y, "Sección", N, 9)
    _t(pg, 528, y, "Orden", N, 9)
    return y + 15


def _aparato(pg, y: float, ap: Aparato) -> float:
    _t(pg, 41, y, f"S{ap.semana}", B, 12)
    _t(pg, 74, y, ap.tipo, B, 12)
    _t(pg, 93, y, "-", B, 12)
    _t(pg, 100, y, ap.control, B, 12)
    return y + 20


def _item(pg, y: float, articulo: str, cantidad: str | None, seccion: str | None, orden: str | None, params: str | None = None, cursiva: bool = False) -> float:
    _t(pg, 52 if cursiva else 48, y, articulo, I if cursiva else B, 8 if cursiva else 9)
    if params:
        _t(pg, 263, y, params, N, 8)
    fuente = I if cursiva else N
    if cantidad is not None:
        _t(pg, 407, y, cantidad, fuente, 8)
    if seccion:
        _t(pg, 478, y, seccion, fuente, 8)
    if orden:
        _t(pg, 528, y, orden, fuente, 8)
    return y + 13


def _pagina_hf(doc, o: OpcionesTanda, seccion: str, grupo: str, bloques: list[tuple]) -> None:
    """bloques: [(numero, titulo, modo, aparato, [items])] items: (articulo, cant, sec, orden, params, cursiva)"""
    pg = doc.new_page(width=595, height=842)
    _cabecera_hf(pg, o, seccion, grupo)
    y = 100
    for numero, titulo, modo, ap, items in bloques:
        y = _orden(pg, y, numero, titulo, modo)
        if ap is not None:
            y = _aparato(pg, y, ap)
        for it in items:
            y = _item(pg, y, *it)
        y += 16


def _pagina_lch(doc, o: OpcionesTanda, ap: Aparato, numero: str, destino: str, pleg: str, control_linea: str | None = None) -> None:
    pg = doc.new_page(width=595, height=842)
    _t(pg, 256, 46, "Hoja de Fabricación", B, 11)
    _t(pg, 429, 56, "F. Emisión:", N, 9)
    _t(pg, 475, 56, o.emision.strftime("%d/%m/%y"), N, 9)
    _t(pg, 241, 65, "SECCIÓN: SC000058-LCH", B, 11)
    _t(pg, 181, 87, f"TANDA {o.tanda}: {o.producto}", B, 11)
    _t(pg, 502, 87, "Página 1 de 1", B, 11)
    _t(pg, 41, 122, "SGe", B, 14)
    _t(pg, 96, 121, f"{ap.tipo}-{ap.control} - SGe PROTECCIONES", N, 11)
    _t(pg, 296, 121, "Grupo Conj: SGe PROTECCIONES", N, 11)
    _t(pg, 494, 121, "Conjunta-Pedido", N, 11)
    _t(pg, 19, 142, f"Semana: {o.emision.year}{ap.semana:02d}", B, 12)
    _t(pg, 159, 142, "ORDEN", B, 12)
    _t(pg, 211, 142, numero, B, 12)
    for x, txt in ((103, "Pieza"), (215, "Cant."), (270, "Dimensiones"), (367, "Pan."), (407, "Corte"), (450, "Pleg."), (493, "Pint."), (534, "Destino")):
        _t(pg, x, 165, txt, B, 9)
    y = 180
    piezas = [("1001-3426041/2-CHAPA PROTECCION", "2", "DC01 1,5 X 2084,8 X 1309,8", None), ("1002-7615105/7-REFUERZO U SUP.", "4", "DC01 1,5 X 119 X 983", pleg)]
    for i, (pz, cant, dims, pl) in enumerate(piezas):
        _t(pg, 17, y, pz, B, 9)
        _t(pg, 224, y, cant, B, 10)
        _t(pg, 242, y, dims, N, 8)
        if pl:
            _t(pg, 446, y, pl, B, 9)
        _t(pg, 525, y, destino.split()[0], N, 8)
        _t(pg, 548, y, destino.split()[1], N, 8)
        ctrl = control_linea if (control_linea and i == 1) else ap.control
        _t(pg, 17, y + 13, f"Nº Control: {ctrl}", N, 8)
        _t(pg, 111, y + 13, "PL=1000 Acabado=0 L=983", N, 8)
        y += 28


def _pagina_bom(doc, o: OpcionesTanda, ap: Aparato, embalaje_of: str) -> None:
    pg = doc.new_page(width=595, height=842)
    _t(pg, 523, 40, o.emision.strftime("%d/%m/%Y"), N, 9)
    _t(pg, 523, 58, ap.control, B, 16)
    _t(pg, 234, 60, "LISTA DE MATERIALES", N, 11)
    _t(pg, 305, 74, "FFP", N, 10)
    _t(pg, 331, 74, "9999", B, 10)
    _t(pg, 537, 78, "Pág.1/1", N, 9)
    _t(pg, 38, 99, "Producto:", B, 9)
    _t(pg, 86, 99, "ELEVADOR DE PRUEBA", B, 10)
    _t(pg, 414, 99, "Embalaje:", B, 9)
    _t(pg, 463, 99, "NORMAL", N, 9)
    _t(pg, 38, 116, "Cliente:", B, 9)
    _t(pg, 86, 116, "CLIENTE DE PRUEBA, S.A.", N, 9)
    _t(pg, 54, 139, "Código", B, 9)
    _t(pg, 115, 139, "Descripcion", B, 9)
    _t(pg, 430, 139, "Cantidad", B, 9)
    y = 160
    for k in range(1, ap.bultos + 1):
        _t(pg, 32, y, f"{k} - B30{k:02d}000/1 - BULTO {k}", B, 10)
        _t(pg, 437, y, f"{1000 + k} x 500 x 400", B, 10)
        _t(pg, 534, y, f"{100 + k} kg", B, 10)
        y += 19
        _t(pg, 32, y, f"30{k:02d}100/1 - COMPONENTE {k}", N, 9)
        _t(pg, 447, y, "1", N, 9)
        y += 19


def _pagina_packing(doc, o: OpcionesTanda, ap: Aparato) -> None:
    pg = doc.new_page(width=595, height=842)
    _t(pg, 394, 26, "CLIENTE", B, 9)
    _t(pg, 440, 26, "CUSTOMER", "hebi", 9)
    _t(pg, 394, 39, "CLIENTE DE PRUEBA, S.A.", N, 9)
    _t(pg, 233, 42, "RELACIÓN DE BULTOS", N, 11)
    _t(pg, 394, 54, "Nº CONTROL /", B, 9)
    _t(pg, 456, 54, "CONTROL NUM.", "hebi", 9)
    _t(pg, 541, 54, ap.control, N, 9)
    _t(pg, 256, 64, "PACKING LIST", I, 11)
    _t(pg, 394, 68, "SU REF.", B, 9)
    _t(pg, 435, 68, "YOUR REF.", "hebi", 9)
    _t(pg, 488, 68, f"REF{ap.control}", N, 9)
    _t(pg, 25, 102, "ELEVADOR DE PRUEBA", B, 10)
    _t(pg, 413, 103, "Dimensiones/Dimensions", N, 8)
    _t(pg, 518, 103, "Peso/Weight", N, 8)
    y = 118
    for k in range(1, ap.bultos + 1):
        _t(pg, 48, y, str(k), B, 10)
        _t(pg, 72, y, f"BULTO {k}", N, 9)
        _t(pg, 421, y, f"{1000 + k} x 500 x 400", N, 9)
        _t(pg, 519, y, f"{100 + k} kg", N, 9)
        y += 12
    _t(pg, 30, 700, "El nº de bultos, peso y dimensiones es aproximada.", B, 8)


def generar_tanda(ruta: Path, o: OpcionesTanda) -> dict:
    """Genera el PDF y devuelve lo que un parser correcto debería encontrar."""
    doc = pymupdf.open()
    esperado = {"ofs": set(), "aparatos": {a.control for a in o.aparatos}, "stubs": set(), "dependencias": set()}
    n = o.base_of
    for ap in o.aparatos:
        of = {k: str(n + i) for i, k in enumerate(["lch", "pleg", "cor", "eh", "pint", "mont", "emb"])}
        n += 10 + ap.ofs_relleno
        ref = f"{ap.tipo}-{ap.control}"
        if o.incluir_lch:
            _pagina_lch(doc, o, ap, of["lch"], f"EH {of['eh']}", of["pleg"], control_linea=("99999" if o.control_ambiguo else None))
            esperado["ofs"].add(of["lch"])
            esperado["stubs"].add(of["pleg"])
            esperado["dependencias"] |= {(of["lch"], of["pleg"]), (of["pleg"], of["eh"]), (of["lch"], of["eh"])}
        if o.incluir_cor:
            _pagina_hf(
                doc, o, "SC000056-COR", "BARANDILLAS",
                [(of["cor"], "PL025286/A - CORTE-TALADRO LASERTUB", "Conjunta", ap, [("3226111/3-TUBO SUPERIOR", "2", "EH", of["eh"], "L=235 N=0", False)])],
            )
            esperado["ofs"].add(of["cor"])
            esperado["dependencias"].add((of["cor"], of["eh"]))
        seccion_eh = "SC000099-XYZ" if o.seccion_desconocida else "SC000001-EH"
        _pagina_hf(
            doc, o, seccion_eh, "SOLDADURA ESTRIBO",
            [(of["eh"], f"{ref} - SOLDADURA ESTRIBO", "Conjunta-Pedido", ap, [("3005100/2-ESTRIBO HO", "1", "TPPINO", of["pint"], "R=1 F=2", False), ("3226111/3-TUBO SUPERIOR", "2", "COR", of["cor"], None, True)])],
        )
        esperado["ofs"].add(of["eh"])
        esperado["dependencias"].add((of["eh"], of["pint"]))
        _pagina_hf(doc, o, "SC000025-TPPINO", "PINTURA POLVO PINO", [(of["pint"], f"{ref} - PINTURA POLVO PINO", "Conjunta-Pedido", ap, [("3005100/2-ESTRIBO HO", "1", "MF", of["mont"], None, False)])])
        esperado["ofs"].add(of["pint"])
        esperado["dependencias"].add((of["pint"], of["mont"]))
        items_mont = [
            ("3001000/4-CONJ. GUIAS-ACCIONAM. HO", None if o.fila_sin_cantidad else str(o.cantidad_montaje), "MF", of["emb"], "R=2670 F=230", False),
            ("3005100/2-ESTRIBO HO", "1", "TPPINO", of["pint"], None, True),
            ("2306164/1-TORN C/HEX M12x20 CINC", "16", None, None, None, True),
        ]
        if o.ciclo:
            items_mont.append(("9999999/1-PIEZA CICLICA", "1", "EH", of["eh"], None, False))  # montaje → soldadura: ciclo
            esperado["dependencias"].add((of["mont"], of["eh"]))
        _pagina_hf(doc, o, "SC000003-MF", "MONTAJE GUIAS-ESTRIBO-CABEZAL", [(of["mont"], f"{ref} - MONTAJE GUIA", "Conjunta-Pedido", ap, items_mont)])
        esperado["ofs"].add(of["mont"])
        esperado["dependencias"].add((of["mont"], of["emb"]))
        if o.omitir_embalaje_de != ap.control:
            _pagina_hf(
                doc, o, "SC000003-MF", "EMBALAJE GUIA-ACCIONA.",
                [(of["emb"], f"{ref} - EMBALAJE GUIA", "Conjunta-Pedido", ap, [("B3001000/1-GUIA-ACCIONAMIENTO", "1", None, None, "L1=3365 L2=510", False), ("3001000/4-CONJ. GUIAS-ACCIONAM. HO", "1", "MF", of["mont"], None, True)])],
            )
            esperado["ofs"].add(of["emb"])
        for k in range(ap.ofs_relleno):
            num = str(int(of["emb"]) + 1 + k)
            _pagina_hf(doc, o, "SC000003-MF", "EMBALAJE ACCESORIOS", [(num, f"{ref} - EMBALAJE ACCESORIOS {k}", "Conjunta-Pedido", ap, [(f"B342{k % 10}000/1-CAJON ACCESORIOS", "1", None, None, "L1=1 L2=2", False), ("2306164/1-TORN C/HEX M12x20 CINC", "8", None, None, None, True)])])
            esperado["ofs"].add(num)
        if o.incluir_bom:
            _pagina_bom(doc, o, ap, of["emb"])
        if o.incluir_packing:
            _pagina_packing(doc, o, ap)
    if o.of_duplicada and o.aparatos:
        ap = o.aparatos[0]
        _pagina_hf(doc, o, "SC000012-ELA", "CABLES MOTOR", [(str(o.base_of + 3), "EH-DUP - CABLES MOTOR", "Conjunta-Pedido", ap, [("6646110/1-CONJ. CABLE", "1", None, None, None, False)])])
    doc.save(ruta, garbage=3, deflate=True)
    paginas = doc.page_count
    doc.close()
    esperado["paginas"] = paginas
    return esperado
