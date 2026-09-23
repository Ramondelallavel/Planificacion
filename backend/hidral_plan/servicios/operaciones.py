"""Derivación de operaciones y tiempos de cada OF.

El PDF de tanda no trae rutas ni tiempos. Por eso:
  * la operación principal se deduce de forma determinista del Grupo HF / título de programa
    con el mapeo configurable "mapeo_operaciones" (fuente DERIVADO, explicada);
  * cuando MRP aporte la ruta real, esas operaciones sustituyen a las derivadas (fuente MRP);
  * la duración sale de la tabla de tiempos estándar (config. de fábrica, MRP o aprendizaje
    aprobado). Si no hay tiempo estándar la duración queda como DATO NO DISPONIBLE y la
    operación no se planifica (se informa en la validación previa del plan).
  * secciones que requieren programación (LCH, LaserTub...): si el documento no trae el
    programa, se crea la operación PROGRAMACION y la de máquina queda "Pendiente de programación".
"""

from __future__ import annotations

from collections import Counter, defaultdict

from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import configuracion
from ..modelos import (
    IncidenciaDatos,
    LineaOF,
    Operacion,
    OrdenFabricacion,
    ProgramaCNC,
    Recurso,
    Seccion,
    TiempoEstandar,
)
from ..modelos.enums import EstadoOF, EstadoOperacion, EstadoProgramacion, Fuente, Severidad

ESTADOS_INICIADOS = {EstadoOperacion.EN_CURSO, EstadoOperacion.PAUSADA, EstadoOperacion.TERMINADA}


def tipo_operacion(of: OrdenFabricacion, seccion: Seccion | None, mapeo: dict) -> tuple[str, str]:
    extra = of.parametros_extra or {}
    if extra.get("tipo_operacion"):
        return extra["tipo_operacion"], "indicado por la columna de la hoja que la referencia"
    if seccion and seccion.flujo in mapeo.get("por_flujo", {}):
        return mapeo["por_flujo"][seccion.flujo], f"flujo de sección {seccion.flujo}"
    textos = [t for t in (of.programa_descripcion, of.grupo_hf, of.descripcion) if t]
    for palabra, tipo in mapeo.get("reglas", []):
        for t in textos:
            if palabra in t.upper():
                return tipo, f"palabra clave '{palabra}' en '{t}'"
    return "GENERICA", "sin palabra clave reconocida en Grupo HF/título"


def recurso_por_alias(of: OrdenFabricacion, recursos: list[Recurso]) -> Recurso | None:
    """Máquina citada explícitamente en el título del programa (p.ej. "CORTE-TALADRO LASERTUB")."""
    texto = " ".join(t for t in (of.programa_descripcion, of.descripcion) if t).upper()
    if not texto:
        return None
    for r in recursos:
        for alias in r.alias or []:
            if alias and alias.upper() in texto:
                return r
    return None


def buscar_tiempo_estandar(tiempos: list[TiempoEstandar], seccion: str | None, grupo: str | None, articulo: str | None, tipo: str) -> TiempoEstandar | None:
    mejor, puntos_mejor = None, -1
    for t in tiempos:
        if t.seccion_codigo != seccion:
            continue
        puntos = 0
        if t.articulo_codigo:
            if t.articulo_codigo != articulo:
                continue
            puntos += 8
        if t.grupo_hf:
            if not grupo or not grupo.upper().startswith(t.grupo_hf.upper()):
                continue
            puntos += 4
        if t.tipo_operacion:
            if t.tipo_operacion != tipo:
                continue
            puntos += 2
        if puntos > puntos_mejor:
            mejor, puntos_mejor = t, puntos
    return mejor


def _familia_setup(of: OrdenFabricacion, lineas: list[LineaOF], tipo: str) -> str | None:
    chapas = Counter((ln.material, ln.espesor_mm) for ln in lineas if ln.material)
    if chapas:
        (mat, esp), _ = chapas.most_common(1)[0]
        return f"{mat} {esp:g} mm" if esp else mat
    if of.consumos:
        return (of.consumos[0].get("articulo") or of.consumos[0].get("descripcion") or "")[:80] or None
    return of.grupo_hf or tipo


def derivar_operaciones(s: Session, of_ids: list[int], documento_id: int | None = None, usuario: str = "sistema") -> dict:
    mapeo = configuracion.obtener(s, "mapeo_operaciones")
    params = configuracion.obtener(s, "planificacion")
    tipos_unidad = set(params.get("unidades_trabajo", []))
    secciones = {sec.codigo: sec for sec in s.scalars(select(Seccion))}
    recursos = list(s.scalars(select(Recurso).where(Recurso.activo.is_(True))))
    tiempos = list(s.scalars(select(TiempoEstandar).where(TiempoEstandar.vigente.is_(True))))
    programas = {p.of_id for p in s.scalars(select(ProgramaCNC).where(ProgramaCNC.of_id.in_(of_ids)))}
    lineas_por_of: dict[int, list[LineaOF]] = defaultdict(list)
    for i in range(0, len(of_ids), 500):
        for ln in s.scalars(select(LineaOF).where(LineaOF.of_id.in_(of_ids[i : i + 500]))):
            lineas_por_of[ln.of_id].append(ln)

    sin_tiempo: dict[tuple, list[str]] = defaultdict(list)
    sin_recurso: dict[tuple, list[str]] = defaultdict(list)
    genericas: list[str] = []
    resumen = Counter()

    for i in range(0, len(of_ids), 500):
        for of in s.scalars(select(OrdenFabricacion).where(OrdenFabricacion.id.in_(of_ids[i : i + 500]))):
            if of.fuente == Fuente.USUARIO:
                continue  # OF creada a mano: sus operaciones las decidió una persona
            sec = secciones.get(of.seccion_codigo or "")
            lineas = lineas_por_of.get(of.id, [])
            tipo, motivo_tipo = tipo_operacion(of, sec, mapeo)
            if tipo == "GENERICA":
                genericas.append(of.numero)
            alias = recurso_por_alias(of, recursos)
            unidades = sum((ln.cantidad or 0) for ln in lineas if ln.tipo in tipos_unidad) or (1.0 if lineas else None)
            n_lineas = sum(1 for ln in lineas if ln.tipo in tipos_unidad)
            if not of.tiene_hoja:
                # OF referenciada: unidades = piezas que la citan (p.ej. plegado desde LCH)
                refs = s.scalars(select(LineaOF).where((LineaOF.orden_plegado == of.numero) | (LineaOF.orden_ref == of.numero))).all()
                unidades = sum(ln.cantidad or 0 for ln in refs) or None
                n_lineas = len(refs)

            # Programación (LCH / LaserTub y demás secciones configuradas como tales)
            requiere = bool(sec and sec.requiere_programacion and tipo in set(params.get("tipos_con_programa", [])))
            if of.programa_codigo:
                if of.id not in programas:
                    s.add(
                        ProgramaCNC(
                            codigo=of.programa_codigo,
                            of_id=of.id,
                            recurso_codigo=alias.codigo if alias else None,
                            fuente=Fuente.PDF,
                            registrado_por="importación PDF",
                            notas=of.programa_descripcion,
                        )
                    )
                    programas.add(of.id)
                estado_prog = EstadoProgramacion.PROGRAMADA if requiere else EstadoProgramacion.NO_REQUIERE
            elif of.id in programas:
                estado_prog = EstadoProgramacion.PROGRAMADA
            elif requiere:
                estado_prog = EstadoProgramacion.PENDIENTE_PROGRAMACION
            else:
                estado_prog = EstadoProgramacion.NO_REQUIERE

            existentes = list(of.operaciones)
            if any(op.estado in ESTADOS_INICIADOS or op.fuente == Fuente.USUARIO for op in existentes):
                # la OF ya está en ejecución, o una persona ha cambiado sus operaciones: no se
                # reestructura, solo se actualizan los tiempos que no se fijaron a mano
                reestructurar = False
            else:
                reestructurar = True
                for op in existentes:
                    op.operacion_anterior_id = None
                s.flush()
                for op in existentes:
                    s.delete(op)
                s.flush()
                of.operaciones = []

            def duracion(tipo_op: str, of=of, lineas=lineas, unidades=unidades, n_lineas=n_lineas) -> tuple[float | None, str, TiempoEstandar | None]:
                articulo = next((ln.articulo_codigo for ln in lineas if ln.tipo in tipos_unidad), None)
                t = buscar_tiempo_estandar(tiempos, of.seccion_codigo, of.grupo_hf, articulo, tipo_op)
                if t is None:
                    return None, f"DATO NO DISPONIBLE: sin tiempo estándar para sección {of.seccion_codigo} / {of.grupo_hf or '-'} / {tipo_op}", None
                if unidades is None:
                    return None, f"DATO NO DISPONIBLE: la OF no tiene cantidades para aplicar el tiempo estándar #{t.id}", t
                minutos = t.minutos_preparacion + t.minutos_por_unidad * unidades + t.minutos_por_linea * n_lineas
                origen = (
                    f"Tiempo estándar #{t.id} v{t.version} ({t.fuente}{', EJEMPLO' if t.es_ejemplo else ''}): "
                    f"{t.minutos_preparacion:g} prep + {t.minutos_por_unidad:g}×{unidades:g} ud + {t.minutos_por_linea:g}×{n_lineas} líneas"
                )
                return round(minutos, 1), origen, t

            if reestructurar:
                seq = 10
                anterior = None
                if estado_prog == EstadoProgramacion.PENDIENTE_PROGRAMACION:
                    dur, origen, te = duracion("PROGRAMACION")
                    prog = Operacion(
                        of_id=of.id,
                        secuencia=5,
                        tipo="PROGRAMACION",
                        descripcion=f"Programación {sec.codigo if sec else ''} de la OF {of.numero}",
                        seccion_codigo=of.seccion_codigo,
                        duracion_estimada_min=dur,
                        origen_duracion=origen,
                        estado=EstadoOperacion.PENDIENTE,
                        fuente=Fuente.DERIVADO,
                        cantidad=unidades,
                        familia_setup=None,
                        tiempo_estandar_id=te.id if te else None,
                    )
                    of.operaciones.append(prog)
                    s.flush()
                    anterior = prog.id
                dur, origen, te = duracion(tipo)
                op = Operacion(
                    tiempo_estandar_id=te.id if te else None,
                    of_id=of.id,
                    secuencia=seq,
                    tipo=tipo,
                    descripcion=f"{of.grupo_hf or of.descripcion or tipo} ({motivo_tipo})",
                    seccion_codigo=of.seccion_codigo,
                    recurso_preferido=alias.codigo if alias else None,
                    duracion_estimada_min=dur,
                    origen_duracion=origen,
                    estado=EstadoOperacion.PENDIENTE_PROGRAMACION if estado_prog == EstadoProgramacion.PENDIENTE_PROGRAMACION else EstadoOperacion.PENDIENTE,
                    requiere_programa=requiere,
                    operacion_anterior_id=anterior,
                    cantidad=unidades,
                    fuente=Fuente.DERIVADO,
                    familia_setup=_familia_setup(of, lineas, tipo),
                )
                of.operaciones.append(op)
                s.flush()
                ops = list(of.operaciones)
            else:
                ops = existentes
                for o in ops:
                    # lo que ha fijado una persona (duración manual, operación añadida) no se recalcula
                    if o.estado not in ESTADOS_INICIADOS and o.fuente != Fuente.USUARIO:
                        o.duracion_estimada_min, o.origen_duracion, te = duracion(o.tipo)
                        o.tiempo_estandar_id = te.id if te else None

            of.estado_programacion = estado_prog
            if estado_prog == EstadoProgramacion.PENDIENTE_PROGRAMACION and of.estado == EstadoOF.NO_INICIADA:
                of.estado = EstadoOF.ESPERANDO_PROGRAMACION
            elif estado_prog != EstadoProgramacion.PENDIENTE_PROGRAMACION and of.estado == EstadoOF.ESPERANDO_PROGRAMACION:
                of.estado = EstadoOF.NO_INICIADA
            of.recurso_requerido = alias.codigo if alias else of.seccion_codigo
            duraciones = [o.duracion_estimada_min for o in ops]
            of.horas_estimadas = round(sum(duraciones) / 60, 2) if duraciones and all(d is not None for d in duraciones) else None
            for o in ops:
                if o.duracion_estimada_min is None:
                    sin_tiempo[(of.seccion_codigo, of.grupo_hf, o.tipo)].append(of.numero)
                candidatos = [
                    r
                    for r in recursos
                    if r.seccion_codigo == o.seccion_codigo
                    and (not r.operaciones or o.tipo in r.operaciones)
                    and (o.tipo != "PROGRAMACION" or r.tipo == "PROGRAMACION")
                    and (o.tipo == "PROGRAMACION" or r.tipo != "PROGRAMACION")
                ]
                if not candidatos:
                    sin_recurso[(of.seccion_codigo, o.tipo)].append(of.numero)
            resumen["ofs"] += 1
            resumen["operaciones"] += len(ops)

    if documento_id is not None:
        for (sec, grupo, tipo), ofs in sin_tiempo.items():
            s.add(
                IncidenciaDatos(
                    documento_id=documento_id,
                    tipo="SIN_TIEMPO_ESTANDAR",
                    severidad=Severidad.ADVERTENCIA,
                    mensaje=f"{len(ofs)} OF de {sec} / {grupo or '-'} ({tipo}) sin tiempo estándar: duración DATO NO DISPONIBLE, no se planificarán hasta configurarlo o importarlo de MRP.",
                    entidad_tipo="SECCION",
                    entidad_ref=sec,
                    alternativas=ofs[:50],
                )
            )
        for (sec, tipo), ofs in sin_recurso.items():
            s.add(
                IncidenciaDatos(
                    documento_id=documento_id,
                    tipo="OPERACION_SIN_RECURSO",
                    severidad=Severidad.ERROR,
                    mensaje=f"{len(ofs)} operaciones {tipo} de la sección {sec} no tienen ningún recurso configurado capaz de hacerlas.",
                    entidad_tipo="SECCION",
                    entidad_ref=sec,
                    alternativas=ofs[:50],
                )
            )
        if genericas:
            s.add(
                IncidenciaDatos(
                    documento_id=documento_id,
                    tipo="OPERACION_NO_MAPEADA",
                    severidad=Severidad.INFO,
                    mensaje=f"{len(genericas)} OF sin palabra clave de operación reconocida: operación GENERICA. Ampliar 'mapeo_operaciones' si procede.",
                    entidad_tipo="OF",
                    alternativas=genericas[:50],
                )
            )
    resumen["sin_tiempo"] = sum(len(v) for v in sin_tiempo.values())
    resumen["sin_recurso"] = sum(len(v) for v in sin_recurso.values())
    return dict(resumen)
