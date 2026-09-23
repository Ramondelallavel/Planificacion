"""Parser de las hojas de órdenes por Grupo HF (formato estándar de la tanda).

Estructura observada en las hojas HIDRAL:

    ORDEN 917251   EH-36747 - MONTAJE GUIA                Conjunta-Pedido
                                         Cantidad   Sección  Orden
    S40 EH - 36747
    3001000/4-CONJ. GUIAS-ACCIONAM. HO  [parámetros]  1  MF  917255   ← salida → OF destino
      3005100/2-ESTRIBO HO (cursiva)                  1  TPPINO 917317 ← componente ← OF origen
      3122010/3-CONJ. CADENA ...  (cursiva)           2  MF  917200

Variantes soportadas en la misma rutina:
  * "Serie" (CIL): el aparato va en la misma fila del artículo ("S40 EH- 36760 6350451/6-...").
  * "Conjunta" (COR / LaserTub / FICEP / GEKA / SABI): título con programa "PL025286/A - CORTE-TALADRO
    LASERTUB", bloque "Consumidos ... Total", identificador de pieza "EH-36747-0305" y detalle de corte "2x235".
  * "Consumidos (suma)": resumen de material al final de la OF.
  * Continuaciones "Página 2 de 3" sin repetir la cabecera de la OF.

Reglas de tipo de línea (deterministas):
  * artículo en letra normal/negrita → SALIDA (Sección/Orden = destino)
  * artículo en cursiva con Orden → ENTRADA (Sección/Orden = OF que lo fabrica)
  * artículo en cursiva sin Orden y con "NxL" → CONSUMO_MATERIAL
  * artículo en cursiva sin Orden → ENTRADA_COMPRA
"""

from __future__ import annotations

from ...modelos.enums import Severidad, TipoLineaOF
from ..contexto import ContextoDocumento
from ..extraccion import PaginaExtraida, Span
from ..maquetacion import Fila, a_numero, agrupar_filas, columna_mas_cercana
from ..registros import RegAviso, RegConsumo, Registro, RegLinea, RegOF
from .comun import (
    MODOS,
    RE_APARATO_FILA,
    RE_APARATO_TITULO,
    RE_ARTICULO,
    RE_CANTIDAD,
    RE_CORTE,
    RE_NUM_OF,
    RE_PIEZA_ID,
    RE_PROGRAMA,
    es_continuacion,
    leer_cabecera,
    reg_aparato_desde_fila,
    registrar_cabecera,
)

X_ZONA_PARAMETROS = 240.0  # a partir de aquí (y antes de Cantidad) está el recuadro de parámetros


def _registrar_of(fila: Fila, idx_orden: int, pagina: PaginaExtraida, ctx: ContextoDocumento, regs: list[Registro]) -> str | None:
    spans = fila.spans
    num_span = spans[idx_orden + 1] if idx_orden + 1 < len(spans) else None
    if num_span is None or not RE_NUM_OF.match(num_span.texto):
        regs.append(
            RegAviso(
                "OF_SIN_NUMERO",
                Severidad.ERROR,
                "Cabecera 'ORDEN' sin número de OF válido. REVISIÓN NECESARIA.",
                pagina.numero,
                fila.texto,
                "OF",
                None,
            )
        )
        return None
    numero = num_span.texto
    resto = [s for s in spans[idx_orden + 2 :]]
    modo = next((s.texto for s in resto if s.texto in MODOS), None)
    titulo = " ".join(s.texto for s in resto if s.texto not in MODOS).strip() or None

    reg = RegOF(
        numero=numero,
        pagina=pagina.numero,
        texto_origen=fila.texto,
        formato="HOJA_GRUPO_HF",
        seccion_codigo=ctx.seccion_codigo,
        seccion_completa=ctx.seccion_completa,
        grupo_hf=ctx.grupo_hf,
        descripcion=titulo,
        modo=modo,
    )
    if titulo:
        if m := RE_PROGRAMA.match(titulo):
            reg.programa_codigo = m.group("prog")
            reg.programa_descripcion = m.group("desc").strip()
        elif m := RE_APARATO_TITULO.match(titulo):
            reg.numero_control_titulo = m.group("ctrl")

    previa = ctx.ofs_vistas.get(numero)
    if previa:
        continuacion_repetida = previa.get("pagina") == pagina.numero - 1 and previa.get("seccion") == ctx.seccion_completa and previa.get("grupo_hf") == ctx.grupo_hf
        if not continuacion_repetida:
            mismo_contexto = previa.get("seccion") == ctx.seccion_completa and previa.get("grupo_hf") == ctx.grupo_hf
            regs.append(
                RegAviso(
                    "OF_DUPLICADA",
                    Severidad.ADVERTENCIA if mismo_contexto else Severidad.CRITICA,
                    (
                        f"La OF {numero} aparece de nuevo (primera vez en página {previa.get('pagina')}"
                        f", sección {previa.get('seccion')}, grupo {previa.get('grupo_hf')}). "
                        + (
                            "Mismo Grupo HF: sus líneas se han acumulado; revisar posible doble conteo."
                            if mismo_contexto
                            else "Sección o Grupo HF distintos: número de OF en conflicto. REVISIÓN NECESARIA."
                        )
                    ),
                    pagina.numero,
                    fila.texto,
                    "OF",
                    numero,
                    alternativas=[previa, {"pagina": pagina.numero, "seccion": ctx.seccion_completa, "grupo_hf": ctx.grupo_hf}],
                )
            )
    ctx.ofs_vistas[numero] = {"pagina": pagina.numero, "seccion": ctx.seccion_completa, "grupo_hf": ctx.grupo_hf}
    regs.append(reg)
    ctx.of_numero = numero
    ctx.of_modo = modo
    ctx.numero_control = None
    ctx.tipo_aparato = None
    ctx.semana_codigo = None
    return numero


def _columnas(fila: Fila) -> dict[str, tuple[float, float]]:
    cols: dict[str, tuple[float, float]] = {}
    for s in fila.spans:
        t = s.texto.strip()
        if t == "Cantidad":
            cols["cantidad"] = (s.x0, s.x1)
        elif t == "Sección":
            cols["seccion"] = (s.x0, s.x1)
        elif t == "Orden":
            cols["orden"] = (s.x0, s.x1)
        elif t == "Total":
            cols["total"] = (s.x0, s.x1)
    return cols


def parsear_hoja_grupo_hf(pagina: PaginaExtraida, ctx: ContextoDocumento) -> list[Registro]:
    regs: list[Registro] = []
    cab = leer_cabecera(pagina)
    regs += registrar_cabecera(cab, pagina, ctx)
    continuacion = es_continuacion(cab, ctx)
    if not continuacion:
        ctx.nueva_hoja()
    ctx.seccion_codigo = cab.seccion_codigo
    ctx.seccion_completa = cab.seccion_completa
    ctx.grupo_hf = cab.grupo_hf
    ctx.pagina_de = cab.pagina_de
    if cab.seccion_codigo is None:
        regs.append(RegAviso("SECCION_AUSENTE", Severidad.ERROR, "Hoja sin 'SECCIÓN:' reconocible.", pagina.numero, cab.texto, "PAGINA", str(pagina.numero)))

    filas = agrupar_filas([s for s in pagina.spans if s.y0 > cab.y_fin + 1])
    estado: str | None = None  # CONSUMIDOS | CONSUMIDOS_SUMA
    ultima: RegLinea | None = None
    avisos_sin_of = 0

    for fila in filas:
        textos = [t.strip() for t in fila.textos()]

        # 1. Cabecera de OF
        if "ORDEN" in textos:
            _registrar_of(fila, textos.index("ORDEN"), pagina, ctx, regs)
            estado, ultima = None, None
            continue

        # 2. Bloques de consumo
        if textos and textos[0].startswith("Consumidos"):
            estado = "CONSUMIDOS_SUMA" if "(suma)" in textos[0] else "CONSUMIDOS"
            cols = _columnas(fila)
            if cols:
                ctx.columnas = {**ctx.columnas, **cols}
            continue

        # 3. Cabecera de columnas
        if "Cantidad" in textos and ("Sección" in textos or "Orden" in textos):
            ctx.columnas = {**ctx.columnas, **_columnas(fila)}
            estado = None
            continue

        if ctx.of_numero is None:
            avisos_sin_of += 1
            if avisos_sin_of <= 3:
                regs.append(
                    RegAviso(
                        "FILA_SIN_OF",
                        Severidad.ADVERTENCIA,
                        "Fila de datos antes de cualquier cabecera 'ORDEN' en la hoja: no se puede asignar a una OF.",
                        pagina.numero,
                        fila.texto,
                        "PAGINA",
                        str(pagina.numero),
                    )
                )
            continue

        # Reparto de la fila en zonas
        col_cant = ctx.columnas.get("cantidad") or ctx.columnas.get("total")
        x_valores = (col_cant[0] - 25) if col_cant else 380.0
        # el texto del artículo puede contener "=" ("TUBERIA RIGIDA ... L=6m"): se decide por posición
        izquierda = [s for s in fila.spans if s.x0 < X_ZONA_PARAMETROS]
        parametros = [s for s in fila.spans if s.x0 < x_valores and s not in izquierda]
        valores = [s for s in fila.spans if s.x0 >= x_valores and s not in parametros]
        texto_izq = " ".join(s.texto for s in izquierda).strip()

        # 4. Filas de consumo de material
        if estado in ("CONSUMIDOS", "CONSUMIDOS_SUMA") and texto_izq:
            m = RE_ARTICULO.match(texto_izq)
            total_txt = valores[0].texto if valores else ""
            regs.append(
                RegConsumo(
                    of_numero=ctx.of_numero,
                    articulo_codigo=m.group("cod") if m else None,
                    descripcion=(m.group("desc") if m else texto_izq).strip(),
                    total=a_numero(total_txt),
                    total_texto=total_txt,
                    pagina=pagina.numero,
                    tipo="Consumidos (suma)" if estado == "CONSUMIDOS_SUMA" else "Consumidos",
                )
            )
            continue

        # 5. Fila de aparato "S40 EH - 36747" (sola o con artículo a continuación: formato Serie)
        articulo_txt = texto_izq
        if m := RE_APARATO_FILA.match(texto_izq):
            reg_ap, aviso = reg_aparato_desde_fila(m.group("tipo"), m.group("ctrl"), int(m.group("sem")), ctx, pagina.numero, fila.texto)
            regs.append(reg_ap)
            if aviso:
                regs.append(aviso)
            articulo_txt = (m.group("resto") or "").strip()
            if not articulo_txt:
                continue

        # 6. Artículo
        if m := RE_ARTICULO.match(articulo_txt):
            span_art = next((s for s in izquierda if m.group("cod") in s.texto), izquierda[-1] if izquierda else None)
            cursiva = bool(span_art and span_art.cursiva)
            cantidad_txt = seccion = orden = None
            for v in valores:
                col = columna_mas_cercana(v, ctx.columnas) if ctx.columnas else None
                if col in ("cantidad", "total") and cantidad_txt is None:
                    cantidad_txt = v.texto
                elif col == "seccion" and seccion is None:
                    seccion = v.texto
                elif col == "orden" and orden is None and RE_NUM_OF.match(v.texto):
                    orden = v.texto
                elif col is None:
                    regs.append(
                        RegAviso(
                            "VALOR_SIN_COLUMNA",
                            Severidad.INFO,
                            f"Valor '{v.texto}' fuera de las columnas conocidas.",
                            pagina.numero,
                            fila.texto,
                            "OF",
                            ctx.of_numero,
                        )
                    )
            detalle = None
            cantidad = None
            if cantidad_txt:
                if mc := RE_CORTE.match(cantidad_txt):
                    detalle = cantidad_txt
                    cantidad = float(mc.group("n"))
                elif RE_CANTIDAD.match(cantidad_txt):
                    cantidad = a_numero(cantidad_txt)
            if cursiva:
                if orden:
                    tipo = TipoLineaOF.ENTRADA_INTERNA if orden == ctx.of_numero else TipoLineaOF.ENTRADA
                elif detalle:
                    tipo = TipoLineaOF.CONSUMO_MATERIAL
                else:
                    tipo = TipoLineaOF.ENTRADA_COMPRA
            else:
                tipo = TipoLineaOF.SALIDA_INTERNA if orden and orden == ctx.of_numero else TipoLineaOF.SALIDA
            linea = RegLinea(
                of_numero=ctx.of_numero,
                tipo=tipo,
                pagina=pagina.numero,
                texto_origen=fila.texto,
                articulo_codigo=m.group("cod"),
                articulo_descripcion=m.group("desc").strip(),
                parametros=" ".join(s.texto for s in parametros).strip() or None,
                cantidad=cantidad,
                cantidad_texto=cantidad_txt,
                detalle_corte=detalle,
                numero_control=ctx.numero_control,
                tipo_aparato=ctx.tipo_aparato,
                semana_codigo=ctx.semana_codigo,
                seccion_ref=seccion,
                orden_ref=orden,
            )
            if cantidad is None and tipo != TipoLineaOF.CONSUMO_MATERIAL:
                regs.append(
                    RegAviso(
                        "CANTIDAD_AUSENTE" if not cantidad_txt else "CANTIDAD_INCOHERENTE",
                        Severidad.ERROR,
                        f"Artículo {linea.articulo_codigo} sin cantidad numérica ('{cantidad_txt or ''}').",
                        pagina.numero,
                        fila.texto,
                        "OF",
                        ctx.of_numero,
                    )
                )
            elif cantidad is not None and cantidad <= 0:
                regs.append(
                    RegAviso(
                        "CANTIDAD_INCOHERENTE",
                        Severidad.ERROR,
                        f"Cantidad no positiva ({cantidad_txt}) en {linea.articulo_codigo}.",
                        pagina.numero,
                        fila.texto,
                        "OF",
                        ctx.of_numero,
                    )
                )
            regs.append(linea)
            ultima = linea
            continue

        # 7. Identificador de pieza (COR): "EH-36747-0305"
        if RE_PIEZA_ID.match(texto_izq) and ultima is not None:
            if ultima.id_pieza and ultima.id_pieza != texto_izq:
                regs.append(
                    RegAviso(
                        "RELACION_AMBIGUA",
                        Severidad.ADVERTENCIA,
                        f"Dos identificadores de pieza para {ultima.articulo_codigo}: {ultima.id_pieza} y {texto_izq}.",
                        pagina.numero,
                        fila.texto,
                        "OF",
                        ctx.of_numero,
                        alternativas=[ultima.id_pieza, texto_izq],
                    )
                )
            else:
                ultima.id_pieza = texto_izq
            if parametros:
                ultima.parametros = ((ultima.parametros or "") + " " + " ".join(s.texto for s in parametros)).strip()
            continue

        # 8. Detalle de corte / consumo bajo la cantidad ("2x235", "1,298")
        if not texto_izq and valores and not parametros and ultima is not None:
            txt = " ".join(v.texto for v in valores)
            ultima.detalle_corte = txt if not ultima.detalle_corte else f"{ultima.detalle_corte} {txt}"
            continue

        # 9. Continuación del recuadro de parámetros
        if not texto_izq and parametros and not valores:
            if ultima is not None:
                ultima.parametros = ((ultima.parametros or "") + " " + " ".join(s.texto for s in parametros)).strip()
            else:
                regs.append(
                    RegAviso(
                        "PARAMETROS_HUERFANOS",
                        Severidad.INFO,
                        "Parámetros al inicio de página sin artículo en esta página (continuación de la anterior).",
                        pagina.numero,
                        fila.texto,
                        "OF",
                        ctx.of_numero,
                    )
                )
            continue

        # 10. Nada reconocible
        regs.append(
            RegAviso(
                "FILA_NO_INTERPRETADA",
                Severidad.ADVERTENCIA,
                "Fila no interpretada por el parser; no se ha inventado ningún dato.",
                pagina.numero,
                fila.texto,
                "OF",
                ctx.of_numero,
            )
        )
    return regs


def _span_texto(spans: list[Span]) -> str:
    return " ".join(s.texto for s in spans)
