"""Parser del formato CAB de puertas batientes.

Dos variantes observadas:
  * SOLD. MARCOS P. BAT.:      "S40-EH-36747  SOLD. MARCOS P. BAT." + "ORDEN 917275" + una casilla
                               gris por unidad con su recuadro de parámetros.
  * MONTAJE-EMBALAJE PUERTAS:  sin fila "ORDEN"; cada casilla trae "Orden 917194" y "Nº Bulto 6",
                               más la "BOLSA ACCESORIOS" con sus componentes.

Los recuadros de parámetros están centrados verticalmente respecto a la casilla gris, por lo
que una línea de parámetros puede aparecer por encima del artículo. Se asignan por proximidad
vertical (≤ 20 pt) y, si no, al artículo anterior.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from ...modelos.enums import Severidad, TipoLineaOF
from ..contexto import ContextoDocumento
from ..extraccion import PaginaExtraida
from ..maquetacion import a_numero, agrupar_filas
from ..registros import RegAviso, RegBulto, Registro, RegLinea, RegOF
from .comun import RE_ARTICULO, RE_NUM_OF, leer_cabecera, reg_aparato_desde_fila, registrar_cabecera

RE_CAB_APARATO = re.compile(r"^S(?P<sem>\d{1,2})-(?P<tipo>[A-Z]{1,4})-(?P<ctrl>\d{4,6})$")
RE_ART_SIN_REV = re.compile(r"^(?P<cod>\d{5,8})\s+(?P<desc>.+)$")


@dataclass
class _Casilla:
    y: float
    codigo: str
    descripcion: str
    texto: str
    parametros: list[str] = field(default_factory=list)
    bulto: str | None = None
    of_numero: str | None = None
    es_bolsa: bool = False
    componentes: list[tuple[str, str, float | None, str]] = field(default_factory=list)


def parsear_hoja_cab(pagina: PaginaExtraida, ctx: ContextoDocumento) -> list[Registro]:
    regs: list[Registro] = []
    cab = leer_cabecera(pagina, y_max=80.0)
    regs += registrar_cabecera(cab, pagina, ctx)
    ctx.nueva_hoja()
    ctx.seccion_codigo = cab.seccion_codigo
    ctx.seccion_completa = cab.seccion_completa
    ctx.grupo_hf = cab.grupo_hf
    ctx.pagina_de = cab.pagina_de

    filas = agrupar_filas([s for s in pagina.spans if s.y0 > cab.y_fin + 1])
    titulo = None
    esperando: str | None = None
    casillas: list[_Casilla] = []
    params: list[tuple[float, str]] = []
    of_actual: str | None = None
    ofs_creadas: set[str] = set()

    def crear_of(numero: str, texto: str, desde_casilla: bool) -> None:
        nonlocal of_actual
        of_actual = numero
        ctx.of_numero = numero
        if numero in ofs_creadas:
            return
        ofs_creadas.add(numero)
        previa = ctx.ofs_vistas.get(numero)
        if previa and previa.get("pagina") not in (pagina.numero, pagina.numero - 1):
            regs.append(
                RegAviso(
                    "OF_DUPLICADA", Severidad.ADVERTENCIA, f"La OF {numero} aparece de nuevo (primera vez en página {previa.get('pagina')}).", pagina.numero, texto, "OF", numero
                )
            )
        ctx.ofs_vistas[numero] = {"pagina": pagina.numero, "seccion": ctx.seccion_completa, "grupo_hf": ctx.grupo_hf}
        regs.append(
            RegOF(
                numero=numero,
                pagina=pagina.numero,
                texto_origen=texto,
                formato="HOJA_CAB_PUERTAS",
                seccion_codigo=ctx.seccion_codigo,
                seccion_completa=ctx.seccion_completa,
                grupo_hf=ctx.grupo_hf,
                descripcion=f"{ctx.tipo_aparato}-{ctx.numero_control} - {titulo}" if ctx.numero_control else titulo,
                numero_control_titulo=ctx.numero_control,
                numero_desde_casilla=desde_casilla,
            )
        )
        if desde_casilla:
            regs.append(
                RegAviso(
                    "OF_DESDE_CASILLA",
                    Severidad.INFO,
                    f"Número de OF {numero} tomado de la casilla 'Orden' (formato CAB montaje-embalaje, sin fila 'ORDEN').",
                    pagina.numero,
                    texto,
                    "OF",
                    numero,
                )
            )

    for fila in filas:
        textos = [t.strip() for t in fila.textos()]
        if textos and (m := RE_CAB_APARATO.match(textos[0])):
            reg_ap, aviso = reg_aparato_desde_fila(m.group("tipo"), m.group("ctrl"), int(m.group("sem")), ctx, pagina.numero, fila.texto)
            regs.append(reg_ap)
            if aviso:
                regs.append(aviso)
            titulo = " ".join(textos[1:]) or ctx.grupo_hf
            continue
        if "ORDEN" in textos:
            i = textos.index("ORDEN")
            if i + 1 < len(textos) and RE_NUM_OF.match(textos[i + 1]):
                crear_of(textos[i + 1], fila.texto, False)
            continue
        restantes = []
        for s in fila.spans:
            t = s.texto.strip()
            if t == "Orden":
                esperando = "ORDEN"
            elif t == "Nº Bulto":
                esperando = "BULTO"
            elif esperando == "ORDEN" and s.negrita and RE_NUM_OF.match(t):
                crear_of(t, fila.texto, of_actual is None or of_actual != t)
                esperando = None
            elif esperando == "BULTO" and s.negrita and re.match(r"^\d{1,3}$", t):
                if casillas:
                    casillas[-1].bulto = t
                esperando = None
            else:
                restantes.append(s)
        if not restantes:
            continue
        izquierda = [s for s in restantes if s.x0 < 250 and "=" not in s.texto]
        derecha_params = [s for s in restantes if "=" in s.texto]
        for s in derecha_params:
            params.append((s.y0, s.texto))
        if not izquierda:
            continue
        txt = " ".join(s.texto for s in izquierda).strip()
        if m := RE_ARTICULO.match(txt):
            # Bolsa de accesorios (código B...) o componente de bolsa
            if txt.startswith("B") and izquierda[0].negrita:
                casillas.append(_Casilla(fila.y, m.group("cod"), m.group("desc").strip(), fila.texto, es_bolsa=True, of_numero=of_actual))
            elif casillas and casillas[-1].es_bolsa:
                qty_span = [s for s in restantes if s not in izquierda and re.match(r"^\d+([.,]\d+)?$", s.texto)]
                cant_txt = qty_span[0].texto if qty_span else ""
                casillas[-1].componentes.append((m.group("cod"), m.group("desc").strip(), a_numero(cant_txt), fila.texto))
            else:
                casillas.append(_Casilla(fila.y, m.group("cod"), m.group("desc").strip(), fila.texto, of_numero=of_actual))
            continue
        if (m := RE_ART_SIN_REV.match(txt)) and izquierda[0].negrita:
            casillas.append(_Casilla(fila.y, m.group("cod"), m.group("desc").strip(), fila.texto, of_numero=of_actual))
            continue
        if casillas and izquierda[0].negrita and len(txt) <= 6 and fila.y - casillas[-1].y < 20:
            casillas[-1].descripcion += " " + txt  # "1H" en la segunda línea de la casilla
            continue
        regs.append(RegAviso("FILA_NO_INTERPRETADA", Severidad.ADVERTENCIA, "Fila CAB no interpretada.", pagina.numero, fila.texto, "OF", of_actual))

    articulos = [c for c in casillas if not c.es_bolsa]
    for y, texto in params:
        if not articulos:
            break
        cercana = min(articulos, key=lambda c: abs(c.y - y))
        if abs(cercana.y - y) > 20:
            anteriores = [c for c in articulos if c.y < y]
            cercana = anteriores[-1] if anteriores else cercana
        cercana.parametros.append(texto)

    for c in casillas:
        if c.of_numero is None:
            regs.append(RegAviso("FILA_SIN_OF", Severidad.ERROR, f"Casilla {c.codigo} sin OF identificable.", pagina.numero, c.texto, "PAGINA", str(pagina.numero)))
            continue
        regs.append(
            RegLinea(
                of_numero=c.of_numero,
                tipo=TipoLineaOF.SALIDA,
                pagina=pagina.numero,
                texto_origen=c.texto,
                articulo_codigo=c.codigo,
                articulo_descripcion=c.descripcion,
                parametros=" ".join(" ".join(c.parametros).split()) or None,
                cantidad=None if c.es_bolsa else 1.0,
                cantidad_texto=None if c.es_bolsa else "1 casilla",
                numero_control=ctx.numero_control,
                tipo_aparato=ctx.tipo_aparato,
                semana_codigo=ctx.semana_codigo,
            )
        )
        for cod, desc, cant, texto in c.componentes:
            regs.append(
                RegLinea(
                    of_numero=c.of_numero,
                    tipo=TipoLineaOF.ENTRADA_COMPRA,
                    pagina=pagina.numero,
                    texto_origen=texto,
                    articulo_codigo=cod,
                    articulo_descripcion=desc,
                    cantidad=cant,
                    numero_control=ctx.numero_control,
                    tipo_aparato=ctx.tipo_aparato,
                    semana_codigo=ctx.semana_codigo,
                )
            )
        if c.bulto and ctx.numero_control:
            regs.append(
                RegBulto(
                    numero_control=ctx.numero_control,
                    numero=c.bulto,
                    pagina=pagina.numero,
                    fuente_detalle="HOJA_CAB",
                    texto_origen=c.texto,
                    of_numero=c.of_numero,
                )
            )
    return regs
