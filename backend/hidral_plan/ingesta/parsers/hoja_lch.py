"""Parser de la "Hoja de Fabricación" de LCH (láser de chapa).

    SG6 | EH-36760 - SG6 NCX PUERTAS EH | Grupo Conj: SG6 NCX PUERTAS EH | Conjunta-Pedido
    Semana: 202640        ORDEN 917332
    Pieza | Cant. | Dimensiones | Pan. | Corte | Pleg. | Pint. | Destino
    1027-7615105/7-REFUERZO U SUP. | 1 | DC01 1,5 X 119 X 983 | | | 917325 | | CAB 917280
    Nº Control: 36760   PL=1000 Mano=I Acabado=0 L=983

Particularidades que se conservan tal cual:
  * posición de pieza en el nido ("1027"),
  * material y dimensiones de chapa ("DC01 1,5 X 119 X 983"),
  * columnas de operaciones Pan./Corte/Pleg./Pint.: si contienen un número de OF, la pieza
    pasa por esa OF antes de su destino (p.ej. plegado 917325),
  * destino = sección + OF que recibe la pieza.
"""

from __future__ import annotations

import re

from ...modelos.enums import Severidad, TipoLineaOF
from ..contexto import ContextoDocumento
from ..extraccion import PaginaExtraida
from ..maquetacion import a_numero, agrupar_filas, columna_mas_cercana
from ..normalizacion import normalizar_semana_larga
from ..registros import RegAparato, RegAviso, Registro, RegLinea, RegOF
from .comun import MODOS, RE_APARATO_TITULO, RE_NUM_OF, leer_cabecera, registrar_cabecera

RE_PIEZA_LCH = re.compile(r"^(?P<pos>\d{1,5})?-(?P<cod>\d{5,8}/[0-9A-Z]+)-(?P<desc>.+)$")
RE_DIMENSIONES = re.compile(r"^(?P<mat>[A-Z0-9\-]+)\s+(?P<esp>\d+(?:[.,]\d+)?)\s*[Xx]\s*(?P<l>\d+(?:[.,]\d+)?)\s*[Xx]\s*(?P<a>\d+(?:[.,]\d+)?)$")
RE_CONTROL = re.compile(r"N[ºo°]\s*Control:\s*(\d{4,6})")
COLUMNAS_OP = ("Pan.", "Corte", "Pleg.", "Pint.")


def parsear_hoja_lch(pagina: PaginaExtraida, ctx: ContextoDocumento) -> list[Registro]:
    regs: list[Registro] = []
    cab = leer_cabecera(pagina, y_max=95.0)
    regs += registrar_cabecera(cab, pagina, ctx)
    ctx.nueva_hoja()
    ctx.seccion_codigo = cab.seccion_codigo
    ctx.seccion_completa = cab.seccion_completa
    ctx.grupo_hf = None
    ctx.pagina_de = cab.pagina_de

    filas = agrupar_filas([s for s in pagina.spans if s.y0 > cab.y_fin + 1])
    bloque: dict = {}
    columnas: dict[str, tuple[float, float]] = {}
    ultima: RegLinea | None = None
    anotaciones = 0

    for fila in filas:
        textos = [t.strip() for t in fila.textos()]
        # Cabecera de bloque: "SGe | EH-36760 - SGe PROTECCIONES | Grupo Conj: ... | Conjunta-Pedido"
        grupo = next((t for t in textos if t.startswith("Grupo Conj:")), None)
        if grupo:
            bloque = {"grupo_conj": grupo.split(":", 1)[1].strip(), "modo": next((t for t in textos if t in MODOS), None)}
            for t in textos:
                if m := RE_APARATO_TITULO.match(t):
                    bloque.update(tipo=m.group("tipo"), ctrl=m.group("ctrl"), descripcion=t)
            bloque["codigo"] = textos[0] if textos and not textos[0].startswith(("EH", "Grupo")) else None
            continue
        # "Semana: 202640   ORDEN 917332"
        if "ORDEN" in textos:
            i = textos.index("ORDEN")
            numero = textos[i + 1] if i + 1 < len(textos) and RE_NUM_OF.match(textos[i + 1]) else None
            semana_txt = next((t for t in textos if t.startswith("Semana")), None)
            semana = normalizar_semana_larga(semana_txt) if semana_txt else None
            if numero is None:
                regs.append(RegAviso("OF_SIN_NUMERO", Severidad.ERROR, "Bloque LCH sin número de OF.", pagina.numero, fila.texto, "OF", None))
                ctx.of_numero = None
                continue
            if semana is None:
                regs.append(
                    RegAviso(
                        "SEMANA_AUSENTE",
                        Severidad.ADVERTENCIA,
                        f"OF {numero} (LCH) sin 'Semana:' válida. Semana: DATO NO DISPONIBLE.",
                        pagina.numero,
                        fila.texto,
                        "OF",
                        numero,
                    )
                )
            previa = ctx.ofs_vistas.get(numero)
            if previa and previa.get("pagina") != pagina.numero - 1:
                regs.append(
                    RegAviso(
                        "OF_DUPLICADA",
                        Severidad.ADVERTENCIA,
                        f"La OF {numero} aparece de nuevo (primera vez en página {previa.get('pagina')}). Líneas acumuladas; revisar.",
                        pagina.numero,
                        fila.texto,
                        "OF",
                        numero,
                    )
                )
            ctx.ofs_vistas[numero] = {"pagina": pagina.numero, "seccion": ctx.seccion_completa, "grupo_hf": bloque.get("grupo_conj")}
            regs.append(
                RegOF(
                    numero=numero,
                    pagina=pagina.numero,
                    texto_origen=fila.texto,
                    formato="HOJA_LCH",
                    seccion_codigo=ctx.seccion_codigo,
                    seccion_completa=ctx.seccion_completa,
                    grupo_hf=bloque.get("grupo_conj"),
                    grupo_conj=bloque.get("grupo_conj"),
                    descripcion=bloque.get("descripcion"),
                    modo=bloque.get("modo"),
                    numero_control_titulo=bloque.get("ctrl"),
                    semana_codigo=semana,
                )
            )
            if bloque.get("ctrl"):
                regs.append(
                    RegAparato(
                        numero_control=bloque["ctrl"],
                        pagina=pagina.numero,
                        texto_origen=bloque.get("descripcion") or fila.texto,
                        referencia=f"{bloque.get('tipo')}-{bloque['ctrl']}",
                        tipo=bloque.get("tipo"),
                        semana_codigo=semana,
                    )
                )
            ctx.of_numero = numero
            ctx.numero_control = bloque.get("ctrl")
            ctx.tipo_aparato = bloque.get("tipo")
            ctx.semana_codigo = semana
            ultima = None
            continue
        # Cabecera de tabla
        if "Pieza" in textos and "Destino" in textos:
            columnas = {}
            for s in fila.spans:
                t = s.texto.strip()
                if t in ("Cant.", "Dimensiones", "Destino", *COLUMNAS_OP):
                    columnas[t] = (s.x0, s.x1)
            continue
        if ctx.of_numero is None:
            continue
        izq = fila.spans[0] if fila.spans else None
        if izq is None:
            continue
        # Fila de pieza
        if m := RE_PIEZA_LCH.match(izq.texto):
            cant_txt = dims_txt = None
            destino: list[str] = []
            ops: list[str] = []
            orden_pleg = None
            for s in fila.spans[1:]:
                col = columna_mas_cercana(s, columnas, margen=18) if columnas else None
                if col == "Destino" or (columnas.get("Destino") and s.x0 >= columnas["Destino"][0] - 15):
                    destino.append(s.texto)
                elif col == "Cant.":
                    cant_txt = s.texto
                elif col == "Dimensiones":
                    dims_txt = s.texto
                elif col in COLUMNAS_OP:
                    ops.append(col)
                    if col == "Pleg." and RE_NUM_OF.match(s.texto):
                        orden_pleg = s.texto
                    elif RE_NUM_OF.match(s.texto):
                        ops[-1] = f"{col}:{s.texto}"
                elif dims_txt is None and RE_DIMENSIONES.match(s.texto):
                    dims_txt = s.texto
            dest_txt = " ".join(destino)
            md = re.match(r"^(?P<sec>[A-Z0-9]+)\s+(?P<of>\d{6,8})$", dest_txt)
            linea = RegLinea(
                of_numero=ctx.of_numero,
                tipo=TipoLineaOF.PIEZA_CHAPA,
                pagina=pagina.numero,
                texto_origen=fila.texto,
                articulo_codigo=m.group("cod"),
                articulo_descripcion=m.group("desc").strip(),
                posicion=m.group("pos"),
                cantidad=a_numero(cant_txt),
                cantidad_texto=cant_txt,
                numero_control=ctx.numero_control,
                tipo_aparato=ctx.tipo_aparato,
                semana_codigo=ctx.semana_codigo,
                seccion_ref=md.group("sec") if md else None,
                orden_ref=md.group("of") if md else None,
                orden_plegado=orden_pleg,
                operaciones_marcadas=ops,
            )
            if dims_txt and (mdim := RE_DIMENSIONES.match(dims_txt)):
                linea.material = mdim.group("mat")
                linea.espesor_mm = a_numero(mdim.group("esp"))
                linea.largo_mm = a_numero(mdim.group("l"))
                linea.ancho_mm = a_numero(mdim.group("a"))
            elif dims_txt:
                regs.append(
                    RegAviso("DIMENSIONES_NO_INTERPRETADAS", Severidad.ADVERTENCIA, f"Dimensiones '{dims_txt}' no interpretadas.", pagina.numero, fila.texto, "OF", ctx.of_numero)
                )
            if not md:
                regs.append(
                    RegAviso(
                        "PIEZA_SIN_DESTINO",
                        Severidad.ERROR,
                        f"Pieza {linea.articulo_codigo} sin destino (sección + OF) legible: '{dest_txt}'.",
                        pagina.numero,
                        fila.texto,
                        "OF",
                        ctx.of_numero,
                    )
                )
            if linea.cantidad is None or linea.cantidad <= 0:
                regs.append(
                    RegAviso(
                        "CANTIDAD_INCOHERENTE", Severidad.ERROR, f"Cantidad '{cant_txt}' no válida en {linea.articulo_codigo}.", pagina.numero, fila.texto, "OF", ctx.of_numero
                    )
                )
            regs.append(linea)
            ultima = linea
            continue
        # Fila "Nº Control: 36760   PL=1000 ..."
        if mc := RE_CONTROL.search(izq.texto):
            if ultima is not None:
                ctrl = mc.group(1)
                if ultima.numero_control and ultima.numero_control != ctrl:
                    regs.append(
                        RegAviso(
                            "RELACION_AMBIGUA",
                            Severidad.ADVERTENCIA,
                            f"Pieza {ultima.articulo_codigo}: Nº Control {ctrl} distinto del aparato del bloque ({ultima.numero_control}). Se conserva el Nº Control de la pieza.",
                            pagina.numero,
                            fila.texto,
                            "OF",
                            ctx.of_numero,
                            alternativas=[ultima.numero_control, ctrl],
                        )
                    )
                ultima.numero_control = ctrl
                params = " ".join(s.texto for s in fila.spans[1:]).strip()
                if params:
                    ultima.parametros = params
            continue
        destino_col = columnas.get("Destino")
        if ultima is not None and destino_col and all(s.x0 >= destino_col[0] - 15 for s in fila.spans):
            # anotación bajo la casilla Destino (p.ej. "NO"): se conserva literal, sin interpretarla
            ultima.operaciones_marcadas.append(f"Destino+{fila.texto.strip()}")
            if not anotaciones:
                regs.append(
                    RegAviso(
                        "ANOTACION_NO_DOCUMENTADA",
                        Severidad.INFO,
                        f"Anotación '{fila.texto.strip()}' bajo la columna Destino: significado no documentado; se conserva literal en la pieza.",
                        pagina.numero,
                        fila.texto,
                        "OF",
                        ctx.of_numero,
                    )
                )
            anotaciones += 1
            continue
        if ultima is not None and all("=" in s.texto for s in fila.spans):
            ultima.parametros = ((ultima.parametros or "") + " " + fila.texto).strip()
            continue
        regs.append(RegAviso("FILA_NO_INTERPRETADA", Severidad.ADVERTENCIA, "Fila LCH no interpretada.", pagina.numero, fila.texto, "OF", ctx.of_numero))
    return regs
