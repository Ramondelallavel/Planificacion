"""Construcción del grafo de fabricación a partir de las líneas persistidas.

Las dependencias salen exclusivamente de los datos:
  * ENTRADA   (cursiva con Sección/Orden) → la OF de la hoja depende de la OF indicada.
  * SALIDA    (Sección/Orden destino)     → la OF destino depende de la OF de la hoja.
  * PIEZA_CHAPA con Pleg. = OF             → corte LCH → OF de plegado → OF destino.
  * Reglas de ruta configuradas por la fábrica (fuente CONFIG_FABRICA), solo si existen.
Las auto-referencias (destino = la propia OF) son montajes internos y no generan dependencia.
"""

from __future__ import annotations

from collections import defaultdict

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..modelos import DependenciaOF, IncidenciaDatos, LineaOF, OFAparato, OrdenFabricacion, ReglaDependencia, Seccion
from ..modelos.enums import Fuente, Severidad, TipoDependencia, TipoLineaOF


def _incidencia(
    s: Session,
    documento_id: int | None,
    tipo: str,
    severidad: str,
    mensaje: str,
    pagina: int | None = None,
    ref: str | None = None,
    entidad: str = "OF",
    texto: str | None = None,
    alternativas: list | None = None,
) -> None:
    s.add(
        IncidenciaDatos(
            documento_id=documento_id,
            pagina=pagina,
            tipo=tipo,
            severidad=severidad,
            mensaje=mensaje,
            entidad_tipo=entidad,
            entidad_ref=ref,
            texto_origen=texto,
            alternativas=alternativas,
        )
    )


def enlazar_aparatos(s: Session, documento_id: int, of_ids: list[int]) -> None:
    """Asigna el aparato principal de cada OF y detecta OF sin aparato o con relación ambigua."""
    rels: dict[int, list[int]] = defaultdict(list)
    for of_id, ap_id in s.execute(select(OFAparato.of_id, OFAparato.aparato_id).where(OFAparato.of_id.in_(of_ids))):
        rels[of_id].append(ap_id)
    from ..modelos import Aparato

    aparatos_por_control = {a.numero_control: a.id for a in s.scalars(select(Aparato))}
    for of in s.scalars(select(OrdenFabricacion).where(OrdenFabricacion.id.in_(of_ids))):
        aps = rels.get(of.id, [])
        titulo = (of.parametros_extra or {}).get("numero_control_titulo")
        if not aps and titulo and titulo in aparatos_por_control:
            ap_id = aparatos_por_control[titulo]
            s.add(OFAparato(of_id=of.id, aparato_id=ap_id, lineas=0))
            aps = [ap_id]
        if len(aps) == 1:
            of.aparato_id = aps[0]
        else:
            of.aparato_id = None
        if titulo and aps and aparatos_por_control.get(titulo) not in aps:
            _incidencia(
                s,
                documento_id,
                "RELACION_AMBIGUA",
                Severidad.ADVERTENCIA,
                f"La OF {of.numero} cita el aparato {titulo} en su título pero sus líneas pertenecen a otros aparatos.",
                (of.paginas or [None])[0],
                of.numero,
                alternativas=[titulo, aps],
            )
        if not aps and of.tiene_hoja:
            _incidencia(
                s,
                documento_id,
                "OF_SIN_APARATO",
                Severidad.ADVERTENCIA if of.modo == "Conjunta-Pedido" else Severidad.INFO,
                f"La OF {of.numero} no tiene ningún aparato identificable en sus líneas.",
                (of.paginas or [None])[0],
                of.numero,
            )


def _seccion_compatible(ref: str | None, real: str | None) -> bool:
    if not ref or not real:
        return True
    return ref == real or real.startswith(ref)  # las hojas LCH truncan la sección (TPPI → TPPINO)


def construir_dependencias(s: Session, documento_id: int, tanda_id: int | None) -> dict[str, int]:
    ofs = {o.numero: o for o in s.scalars(select(OrdenFabricacion).where(OrdenFabricacion.documento_id == documento_id))}
    ids_doc = [o.id for o in ofs.values()]
    # solo se cargan las OF citadas por este documento o de su tanda (no todo el histórico)
    citadas: set[str] = set()
    for ref, pleg in s.execute(select(LineaOF.orden_ref, LineaOF.orden_plegado).where(LineaOF.of_id.in_(ids_doc)).distinct()):
        citadas.update(x for x in (ref, pleg) if x)
    todas: dict[str, OrdenFabricacion] = dict(ofs)
    faltan = citadas - set(todas)
    for i in range(0, len(faltan), 500):
        lote = list(faltan)[i : i + 500]
        todas.update({o.numero: o for o in s.scalars(select(OrdenFabricacion).where(OrdenFabricacion.numero.in_(lote)))})
    if tanda_id is not None:
        todas.update({o.numero: o for o in s.scalars(select(OrdenFabricacion).where(OrdenFabricacion.tanda_id == tanda_id))})
    aristas: dict[tuple[int, int], dict] = {}
    referencias_sin_hoja: dict[str, dict] = {}
    truncadas = 0

    def asegurar_of(numero: str, seccion: str | None, pagina: int | None, motivo: str) -> OrdenFabricacion:
        of = todas.get(numero)
        if of is None:
            of = OrdenFabricacion(
                numero=numero,
                tanda_id=tanda_id,
                seccion_codigo=seccion,
                tiene_hoja=False,
                fuente=Fuente.PDF,
                documento_id=documento_id,
                descripcion=f"OF referenciada ({motivo}); sin hoja en el documento",
                paginas=[],
            )
            s.add(of)
            s.flush()
            todas[numero] = of
            referencias_sin_hoja[numero] = {"seccion": seccion, "pagina": pagina, "motivo": motivo}
        return of

    def arista(origen: OrdenFabricacion, destino: OrdenFabricacion, tipo: str, linea: LineaOF) -> None:
        if origen.id == destino.id:
            return
        clave = (origen.id, destino.id)
        ev = {"pagina": linea.pagina, "articulo": linea.articulo_codigo, "tipo": tipo}
        if clave not in aristas:
            aristas[clave] = {"tipo": tipo, "evidencias": [ev]}
        elif len(aristas[clave]["evidencias"]) < 20:
            aristas[clave]["evidencias"].append(ev)

    lineas = s.scalars(select(LineaOF).where(LineaOF.of_id.in_(ids_doc), (LineaOF.orden_ref.is_not(None)) | (LineaOF.orden_plegado.is_not(None)))).yield_per(500)
    of_por_id = {o.id: o for o in ofs.values()}
    for ln in lineas:
        propia = of_por_id[ln.of_id]
        ref = asegurar_of(ln.orden_ref, ln.seccion_ref, ln.pagina, f"columna Orden/Destino de la OF {propia.numero}") if ln.orden_ref else None
        if ref is not None and ref.id != propia.id and not _seccion_compatible(ln.seccion_ref, ref.seccion_codigo):
            _incidencia(
                s,
                documento_id,
                "SECCION_INCOHERENTE",
                Severidad.ADVERTENCIA,
                f"La OF {propia.numero} cita la OF {ref.numero} en la sección {ln.seccion_ref}, pero esa OF es de la sección {ref.seccion_codigo}.",
                ln.pagina,
                propia.numero,
                texto=ln.texto_origen,
                alternativas=[ln.seccion_ref, ref.seccion_codigo],
            )
        elif ref is not None and ln.seccion_ref and ref.seccion_codigo and ln.seccion_ref != ref.seccion_codigo:
            truncadas += 1
        if ln.tipo == TipoLineaOF.ENTRADA and ref is not None:
            arista(ref, propia, TipoDependencia.COMPONENTE, ln)
        elif ln.tipo == TipoLineaOF.SALIDA and ref is not None:
            arista(propia, ref, TipoDependencia.DESTINO, ln)
        elif ln.tipo == TipoLineaOF.PIEZA_CHAPA:
            if ln.orden_plegado:
                pleg = asegurar_of(ln.orden_plegado, propia.seccion_codigo, ln.pagina, f"columna Pleg. de la OF {propia.numero}")
                extra = dict(pleg.parametros_extra or {})
                if not pleg.tiene_hoja and extra.get("tipo_operacion") != "PLEGADO":
                    extra["tipo_operacion"] = "PLEGADO"
                    pleg.parametros_extra = extra
                    if not pleg.grupo_hf:
                        pleg.grupo_hf = "PLEGADO"
                arista(propia, pleg, TipoDependencia.PLEGADO, ln)
                if ref is not None:
                    arista(pleg, ref, TipoDependencia.DESTINO, ln)
            elif ref is not None:
                arista(propia, ref, TipoDependencia.DESTINO, ln)

    # Reglas de ruta configuradas (solo si la fábrica las ha definido)
    reglas = list(s.scalars(select(ReglaDependencia).where(ReglaDependencia.activa.is_(True))))
    if reglas:
        por_grupo_aparato: dict[tuple[str, int | None], list[OrdenFabricacion]] = defaultdict(list)
        for of in todas.values():
            if of.tanda_id == tanda_id and of.grupo_hf:
                por_grupo_aparato[(of.grupo_hf, of.aparato_id)].append(of)
        for regla in reglas:
            for (grupo, ap), lista in list(por_grupo_aparato.items()):
                if not grupo.startswith(regla.grupo_hf_origen):
                    continue
                for (grupo_d, ap_d), destinos in por_grupo_aparato.items():
                    if not grupo_d.startswith(regla.grupo_hf_destino) or (regla.mismo_aparato and ap != ap_d) or ap is None:
                        continue
                    for o in lista:
                        for d in destinos:
                            if o.id != d.id and (o.id, d.id) not in aristas:
                                aristas[(o.id, d.id)] = {
                                    "tipo": TipoDependencia.REGLA_CONFIG,
                                    "evidencias": [{"regla": regla.id, "descripcion": regla.descripcion, "ejemplo": regla.es_ejemplo}],
                                    "fuente": Fuente.CONFIG_FABRICA,
                                }

    existentes = {(d.of_origen_id, d.of_destino_id): d for d in s.scalars(select(DependenciaOF).where(DependenciaOF.of_destino_id.in_([o.id for o in todas.values()])))}
    nuevas = 0
    for (o, d), datos in aristas.items():
        dep = existentes.get((o, d))
        if dep is None:
            s.add(DependenciaOF(of_origen_id=o, of_destino_id=d, tipo=datos["tipo"], evidencias=datos["evidencias"], fuente=datos.get("fuente", Fuente.PDF)))
            nuevas += 1
        else:
            dep.evidencias = datos["evidencias"]
            dep.activa = True
    for numero, info in referencias_sin_hoja.items():
        _incidencia(
            s,
            documento_id,
            "OF_REFERENCIADA_SIN_HOJA",
            Severidad.INFO,
            f"La OF {numero} ({info['seccion'] or 'sección desconocida'}) se cita en {info['motivo']} pero no tiene hoja en este documento. Se registra como OF referenciada; sus datos de detalle: DATO NO DISPONIBLE.",
            info["pagina"],
            numero,
        )
    if truncadas:
        _incidencia(
            s,
            documento_id,
            "SECCION_ABREVIADA",
            Severidad.INFO,
            f"{truncadas} referencias citan la sección abreviada (p.ej. 'TPPI' por 'TPPINO' en hojas LCH); se han considerado coherentes por prefijo.",
            None,
            None,
            entidad="DOCUMENTO",
        )
    s.flush()
    return {"dependencias": len(aristas), "nuevas": nuevas, "ofs_referenciadas": len(referencias_sin_hoja)}


def detectar_ciclos(s: Session, documento_id: int | None, of_ids: set[int] | None = None) -> list[list[str]]:
    """Tarjan (iterativo) sobre el grafo de dependencias activas."""
    q = select(DependenciaOF.of_origen_id, DependenciaOF.of_destino_id).where(DependenciaOF.activa.is_(True))
    ady: dict[int, list[int]] = defaultdict(list)
    nodos: set[int] = set()
    for o, d in s.execute(q):
        if of_ids is None or (o in of_ids and d in of_ids):
            ady[o].append(d)
            nodos.update((o, d))
    indice: dict[int, int] = {}
    bajo: dict[int, int] = {}
    en_pila: set[int] = set()
    pila: list[int] = []
    componentes: list[list[int]] = []
    contador = 0
    for raiz in nodos:
        if raiz in indice:
            continue
        trabajo = [(raiz, 0)]
        while trabajo:
            v, i = trabajo.pop()
            if i == 0:
                indice[v] = bajo[v] = contador
                contador += 1
                pila.append(v)
                en_pila.add(v)
            recursion = False
            vecinos = ady.get(v, [])
            for j in range(i, len(vecinos)):
                w = vecinos[j]
                if w not in indice:
                    trabajo.append((v, j + 1))
                    trabajo.append((w, 0))
                    recursion = True
                    break
                if w in en_pila:
                    bajo[v] = min(bajo[v], indice[w])
            if recursion:
                continue
            if bajo[v] == indice[v]:
                comp = []
                while True:
                    w = pila.pop()
                    en_pila.discard(w)
                    comp.append(w)
                    if w == v:
                        break
                if len(comp) > 1:
                    componentes.append(comp)
            if trabajo:
                padre = trabajo[-1][0]
                bajo[padre] = min(bajo[padre], bajo[v])
    numeros = dict(s.execute(select(OrdenFabricacion.id, OrdenFabricacion.numero)).all())
    ciclos = [[numeros[i] for i in comp] for comp in componentes]
    for ciclo in ciclos:
        _incidencia(
            s,
            documento_id,
            "DEPENDENCIA_CIRCULAR",
            Severidad.CRITICA,
            f"Dependencia circular entre las OF {', '.join(sorted(ciclo))}. Ninguna puede empezar antes que las demás: REVISIÓN NECESARIA.",
            None,
            ",".join(sorted(ciclo))[:64],
            alternativas=sorted(ciclo),
        )
    return ciclos


def asegurar_secciones(s: Session, documento_id: int) -> list[str]:
    """Registra como desconocidas las secciones del documento que la fábrica no ha configurado."""
    conocidas = {sec.codigo for sec in s.scalars(select(Seccion))}
    usadas: dict[str, str | None] = {}
    for cod, completa in s.execute(select(OrdenFabricacion.seccion_codigo, OrdenFabricacion.seccion_completa).where(OrdenFabricacion.documento_id == documento_id).distinct()):
        if cod:
            usadas.setdefault(cod, completa)
    nuevas = []
    for cod, completa in usadas.items():
        if cod not in conocidas:
            s.add(Seccion(codigo=cod, codigo_completo=completa, nombre=None, conocida=False, fuente=Fuente.PDF))
            nuevas.append(cod)
            _incidencia(
                s,
                documento_id,
                "SECCION_DESCONOCIDA",
                Severidad.ADVERTENCIA,
                f"La sección {completa or cod} no está en la configuración de fábrica: sin recursos asociados sus OF no se podrán planificar.",
                None,
                cod,
                entidad="SECCION",
            )
    return nuevas
