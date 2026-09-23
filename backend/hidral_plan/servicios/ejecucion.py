"""Ejecución en planta: pantalla del operario, fichajes y aprendizaje de tiempos (puntos 25-27).

Reglas duras al fichar (no se pueden saltar salvo autorización registrada de un supervisor):
  * el operario debe estar cualificado para el recurso;
  * las operaciones precedentes deben estar terminadas;
  * una operación pendiente de programación no puede iniciarse;
  * el recurso no puede estar averiado;
  * un operario no puede tener dos fichajes abiertos a la vez.
"""

from __future__ import annotations

import statistics
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import configuracion
from ..modelos import (
    Aparato,
    AsignacionPlan,
    DependenciaOF,
    EstimacionPropuesta,
    Fichaje,
    Notificacion,
    Operacion,
    Operario,
    OrdenFabricacion,
    Recurso,
    TiempoEstandar,
)
from ..modelos.comun import ahora as _ahora
from ..modelos.enums import EstadoOF, EstadoOperacion, EstadoRecurso, Fuente
from .auditoria import auditar


class FichajeRechazado(Exception):
    def __init__(self, errores: list[str]):
        super().__init__("; ".join(errores))
        self.errores = errores


def _plan_activo(s: Session):
    from ..planificacion.servicio import plan_activo

    return plan_activo(s)


def _tarjeta(s: Session, a: AsignacionPlan | None, op: Operacion, ahora: datetime) -> dict:
    of = s.get(OrdenFabricacion, op.of_id)
    ap = s.get(Aparato, of.aparato_id) if of and of.aparato_id else None
    rec = s.get(Recurso, a.recurso_id) if a and a.recurso_id else None
    bloqueos = motivos_no_inicio(s, op, rec, None)
    return {
        "operacion_id": op.id,
        "of": of.numero if of else None,
        "of_id": op.of_id,
        "aparato": ap.referencia if ap else ("varios" if of and of.aparato_id is None else None),
        "tanda": of.tanda_id if of else None,
        "operacion": op.tipo,
        "descripcion": op.descripcion,
        "maquina": rec.codigo if rec else None,
        "maquina_nombre": rec.nombre if rec else None,
        "cantidad": op.cantidad,
        "cantidad_hecha": op.cantidad_hecha,
        "tiempo_estimado_min": op.duracion_estimada_min,
        "inicio_previsto": a.inicio.isoformat() if a else None,
        "fin_previsto": a.fin.isoformat() if a else None,
        "provisional": bool(a and a.provisional),
        "puede_iniciar": not bloqueos,
        "bloqueos": bloqueos,
        "grupo_hf": of.grupo_hf if of else None,
        "programa": of.programa_codigo if of else None,
    }


def motivos_no_inicio(s: Session, op: Operacion, recurso: Recurso | None, operario: Operario | None) -> list[str]:
    motivos: list[str] = []
    if op.estado == EstadoOperacion.TERMINADA:
        motivos.append("La operación ya está terminada")
    if op.estado == EstadoOperacion.PENDIENTE_PROGRAMACION:
        motivos.append("Pendiente de programación: falta el programa de máquina")
    if recurso is not None and recurso.estado != EstadoRecurso.OPERATIVO:
        motivos.append(f"El recurso {recurso.codigo} está {recurso.estado}")
    if operario is not None and recurso is not None:
        codigos = {c.recurso_codigo for c in operario.cualificaciones}
        tipos = {c.tipo_operacion for c in operario.cualificaciones}
        if recurso.codigo not in codigos and op.tipo not in tipos:
            motivos.append(f"{operario.nombre} no está cualificado para {recurso.codigo}")
    # precedencias: operaciones anteriores de la misma OF y OF predecesoras
    for otra in s.scalars(select(Operacion).where(Operacion.of_id == op.of_id, Operacion.secuencia < op.secuencia)):
        if otra.estado != EstadoOperacion.TERMINADA:
            motivos.append(f"Falta terminar la operación {otra.tipo} de la misma OF")
    preds = s.scalars(select(DependenciaOF.of_origen_id).where(DependenciaOF.of_destino_id == op.of_id, DependenciaOF.activa.is_(True))).all()
    for pid in preds:
        p = s.get(OrdenFabricacion, pid)
        if p and p.estado not in (EstadoOF.TERMINADA, EstadoOF.VALIDADA):
            if p.disponible_prevista is not None and p.disponible_prevista <= _ahora():
                continue
            motivos.append(f"Falta la OF predecesora {p.numero} ({p.seccion_codigo or '?'}, {p.estado})")
    return motivos


def trabajo_operario(s: Session, operario_id: int, ahora: datetime) -> dict:
    o = s.get(Operario, operario_id)
    if o is None:
        raise ValueError("Operario inexistente")
    abierto = s.scalar(select(Fichaje).where(Fichaje.operario_id == operario_id, Fichaje.estado.in_(["ABIERTO", "PAUSADO"])))
    plan = _plan_activo(s)
    asigs = []
    if plan:
        asigs = list(s.scalars(select(AsignacionPlan).where(AsignacionPlan.plan_id == plan.id, AsignacionPlan.operario_id == operario_id).order_by(AsignacionPlan.inicio)))
    pendientes = []
    for a in asigs:
        op = s.get(Operacion, a.operacion_id)
        if op and op.estado != EstadoOperacion.TERMINADA and (not abierto or op.id != abierto.operacion_id):
            pendientes.append(_tarjeta(s, a, op, ahora))
    actual = None
    if abierto:
        op = s.get(Operacion, abierto.operacion_id)
        a = next((x for x in asigs if x.operacion_id == abierto.operacion_id), None)
        actual = _tarjeta(s, a, op, ahora)
        actual.update(fichaje_id=abierto.id, estado_fichaje=abierto.estado, fichaje_inicio=abierto.inicio.isoformat())
        actual["bloqueos"] = []
        actual["puede_iniciar"] = False
    avisos = [
        {"id": n.id, "titulo": n.titulo, "mensaje": n.mensaje, "fecha": n.fecha.isoformat(), "nivel": n.nivel}
        for n in s.scalars(select(Notificacion).where(Notificacion.operario_id == operario_id, Notificacion.leida.is_(False)).order_by(Notificacion.fecha.desc()).limit(5))
    ]
    return {
        "operario": {"id": o.id, "codigo": o.codigo_empleado, "nombre": o.nombre, "turno": o.turno_codigo},
        "actual": actual,
        "siguiente": pendientes[0] if pendientes else None,
        "despues": pendientes[1:4],
        "avisos": avisos,
    }


def iniciar(s: Session, operario_id: int, operacion_id: int, usuario: str, ahora: datetime, recurso_id: int | None = None, autorizado_por: str | None = None) -> dict:
    op = s.get(Operacion, operacion_id)
    o = s.get(Operario, operario_id)
    if op is None or o is None:
        raise FichajeRechazado(["Operación u operario inexistente"])
    if s.scalar(select(Fichaje).where(Fichaje.operario_id == operario_id, Fichaje.estado.in_(["ABIERTO", "PAUSADO"]))):
        raise FichajeRechazado(["Ya tienes un trabajo abierto: termínalo o páusalo primero"])
    if recurso_id is None:
        plan = _plan_activo(s)
        a = s.scalar(select(AsignacionPlan).where(AsignacionPlan.plan_id == plan.id, AsignacionPlan.operacion_id == operacion_id)) if plan else None
        recurso_id = a.recurso_id if a else None
    rec = s.get(Recurso, recurso_id) if recurso_id else None
    if rec is None:
        raise FichajeRechazado(["La operación no tiene recurso asignado en el plan: indique el recurso"])
    motivos = motivos_no_inicio(s, op, rec, o)
    duros = [m for m in motivos if "terminada" in m or "programación" in m or "cualificado" in m or "está AVERIADO" in m or "está PARADO" in m]
    blandos = [m for m in motivos if m not in duros]
    if duros:
        raise FichajeRechazado(duros)
    if blandos and not autorizado_por:
        raise FichajeRechazado(blandos + ["Un supervisor puede autorizar el inicio anticipado (queda registrado)"])
    f = Fichaje(
        operario_id=operario_id,
        of_id=op.of_id,
        operacion_id=op.id,
        recurso_id=rec.id,
        inicio=ahora,
        estado="ABIERTO",
        duracion_planificada_min=op.duracion_estimada_min,
        forzado_por=autorizado_por if blandos else None,
    )
    s.add(f)
    op.estado = EstadoOperacion.EN_CURSO
    of = s.get(OrdenFabricacion, op.of_id)
    if of:
        of.estado = EstadoOF.EN_CURSO
        of.fecha_real_inicio = of.fecha_real_inicio or ahora
    s.flush()
    auditar(
        s,
        usuario,
        "FICHAJE_INICIO",
        "OPERACION",
        op.id,
        despues={"operario": o.codigo_empleado, "recurso": rec.codigo, "autorizado_por": autorizado_por, "excepciones": blandos or None},
    )
    return {"fichaje_id": f.id, "estado": "EN_CURSO"}


def pausar(s: Session, fichaje_id: int, usuario: str, ahora: datetime, motivo: str | None = None) -> dict:
    f = s.get(Fichaje, fichaje_id)
    if f is None or f.estado != "ABIERTO":
        raise FichajeRechazado(["El fichaje no está abierto"])
    f.estado = "PAUSADO"
    f.pausas = list(f.pausas or []) + [{"inicio": ahora.isoformat(), "fin": None, "motivo": motivo}]
    op = s.get(Operacion, f.operacion_id)
    op.estado = EstadoOperacion.PAUSADA
    of = s.get(OrdenFabricacion, f.of_id)
    of.estado = EstadoOF.PAUSADA
    auditar(s, usuario, "FICHAJE_PAUSA", "OPERACION", f.operacion_id, motivo=motivo)
    return {"estado": "PAUSADO"}


def reanudar(s: Session, fichaje_id: int, usuario: str, ahora: datetime) -> dict:
    f = s.get(Fichaje, fichaje_id)
    if f is None or f.estado != "PAUSADO":
        raise FichajeRechazado(["El fichaje no está en pausa"])
    pausas = list(f.pausas or [])
    if pausas and pausas[-1]["fin"] is None:
        pausas[-1] = {**pausas[-1], "fin": ahora.isoformat()}
        f.minutos_pausa = (f.minutos_pausa or 0) + (ahora - datetime.fromisoformat(pausas[-1]["inicio"])).total_seconds() / 60
    f.pausas = pausas
    f.estado = "ABIERTO"
    s.get(Operacion, f.operacion_id).estado = EstadoOperacion.EN_CURSO
    s.get(OrdenFabricacion, f.of_id).estado = EstadoOF.EN_CURSO
    auditar(s, usuario, "FICHAJE_REANUDA", "OPERACION", f.operacion_id)
    return {"estado": "EN_CURSO"}


def terminar(s: Session, fichaje_id: int, usuario: str, ahora: datetime, cantidad: float | None = None, parcial: bool = False) -> dict:
    f = s.get(Fichaje, fichaje_id)
    if f is None or f.estado not in ("ABIERTO", "PAUSADO"):
        raise FichajeRechazado(["El fichaje no está abierto"])
    if f.estado == "PAUSADO":
        reanudar(s, fichaje_id, usuario, ahora)
    f.fin = ahora
    f.estado = "CERRADO"
    f.cantidad = cantidad
    f.duracion_real_min = round((ahora - f.inicio).total_seconds() / 60 - (f.minutos_pausa or 0), 1)
    op = s.get(Operacion, f.operacion_id)
    op.duracion_real_min = round((op.duracion_real_min or 0) + f.duracion_real_min, 1)
    op.cantidad_hecha = (op.cantidad_hecha or 0) + (cantidad if cantidad is not None else (op.cantidad or 0) if not parcial else 0)
    completa = not parcial and (op.cantidad is None or op.cantidad_hecha + 1e-6 >= op.cantidad)
    op.estado = EstadoOperacion.TERMINADA if completa else EstadoOperacion.PENDIENTE
    of = s.get(OrdenFabricacion, f.of_id)
    of.horas_reales = round((of.horas_reales or 0) + f.duracion_real_min / 60, 2)
    ops = list(s.scalars(select(Operacion).where(Operacion.of_id == of.id)))
    if all(o.estado == EstadoOperacion.TERMINADA for o in ops):
        of.estado = EstadoOF.TERMINADA
        of.fecha_real_fin = ahora
    else:
        of.estado = EstadoOF.PLANIFICADA
    auditar(
        s,
        usuario,
        "FICHAJE_FIN",
        "OPERACION",
        op.id,
        despues={
            "real_min": f.duracion_real_min,
            "planificado_min": f.duracion_planificada_min,
            "cantidad": cantidad,
            "operacion_terminada": completa,
            "of_terminada": of.estado == EstadoOF.TERMINADA,
        },
    )
    return {
        "estado": op.estado,
        "of_estado": of.estado,
        "duracion_real_min": f.duracion_real_min,
        "duracion_planificada_min": f.duracion_planificada_min,
        "desviacion_min": None if f.duracion_planificada_min is None else round(f.duracion_real_min - f.duracion_planificada_min, 1),
    }


# ------------------------------------------------------------------ aprendizaje de tiempos
def proponer_estimaciones(s: Session) -> list[dict]:
    """Compara tiempo real frente a planificado por tiempo estándar. Solo PROPONE."""
    cfg = configuracion.obtener(s, "aprendizaje")
    minimo, desv = int(cfg.get("muestras_minimas", 5)), float(cfg.get("desviacion_minima", 0.10))
    # una muestra por operación terminada (aunque tenga varios fichajes: el real ya está acumulado)
    por_te: dict[int, dict[int, float]] = {}
    for _f, op in s.execute(
        select(Fichaje, Operacion)
        .join(Operacion, Operacion.id == Fichaje.operacion_id)
        .where(Fichaje.estado == "CERRADO", Operacion.estado == EstadoOperacion.TERMINADA, Operacion.tiempo_estandar_id.is_not(None))
    ):
        if op.duracion_estimada_min and op.duracion_real_min:
            por_te.setdefault(op.tiempo_estandar_id, {})[op.id] = op.duracion_real_min / op.duracion_estimada_min
    nuevas = []
    for te_id, muestras in por_te.items():
        rs = list(muestras.values())
        if len(rs) < minimo:
            continue
        mediana = statistics.median(rs)
        if abs(mediana - 1) < desv:
            continue
        if s.scalar(select(EstimacionPropuesta).where(EstimacionPropuesta.tiempo_estandar_id == te_id, EstimacionPropuesta.estado == "PROPUESTA")):
            continue
        te = s.get(TiempoEstandar, te_id)
        if te is None or not te.vigente:
            continue
        prop = EstimacionPropuesta(
            tiempo_estandar_id=te_id,
            muestras=len(rs),
            ratio_real_planificado=round(mediana, 3),
            minutos_por_unidad_actual=te.minutos_por_unidad,
            minutos_por_unidad_propuesto=round(te.minutos_por_unidad * mediana, 2),
            explicacion=(
                f"{len(rs)} operaciones terminadas con este tiempo estándar ({te.seccion_codigo}/{te.grupo_hf or '-'}/{te.tipo_operacion or '-'}): "
                f"el real es la mediana ×{mediana:.2f} del planificado (rango ×{min(rs):.2f}–×{max(rs):.2f}). Se propone ajustar preparación y minutos/unidad en la misma proporción."
            ),
        )
        s.add(prop)
        nuevas.append(prop)
    s.flush()
    return [{"id": p.id, "tiempo_estandar_id": p.tiempo_estandar_id, "muestras": p.muestras, "ratio": p.ratio_real_planificado, "explicacion": p.explicacion} for p in nuevas]


def decidir_estimacion(s: Session, propuesta_id: int, aprobar: bool, usuario: str) -> dict:
    p = s.get(EstimacionPropuesta, propuesta_id)
    if p is None or p.estado != "PROPUESTA":
        raise ValueError("Propuesta inexistente o ya decidida")
    p.estado = "APROBADA" if aprobar else "RECHAZADA"
    p.decidida_por, p.decidida = usuario, _ahora()
    resultado: dict = {"estado": p.estado}
    if aprobar:
        te = s.get(TiempoEstandar, p.tiempo_estandar_id)
        nuevo = TiempoEstandar(
            seccion_codigo=te.seccion_codigo,
            grupo_hf=te.grupo_hf,
            articulo_codigo=te.articulo_codigo,
            tipo_operacion=te.tipo_operacion,
            minutos_preparacion=round(te.minutos_preparacion * p.ratio_real_planificado, 2),
            minutos_por_unidad=p.minutos_por_unidad_propuesto,
            minutos_por_linea=round(te.minutos_por_linea * p.ratio_real_planificado, 2),
            fuente=Fuente.APRENDIZAJE,
            es_ejemplo=te.es_ejemplo,
            version=te.version + 1,
            vigente=True,
            creado_por=usuario,
            notas=f"Aprobado desde propuesta #{p.id}; sustituye a #{te.id} (reversible)",
        )
        te.vigente = False
        s.add(nuevo)
        s.flush()
        from .operaciones import derivar_operaciones

        ofs = [of_id for (of_id,) in s.execute(select(Operacion.of_id).where(Operacion.tiempo_estandar_id == te.id, Operacion.estado != EstadoOperacion.TERMINADA).distinct())]
        derivar_operaciones(s, ofs)
        resultado.update(tiempo_estandar_nuevo=nuevo.id, ofs_recalculadas=len(ofs))
    auditar(s, usuario, "APROBAR_ESTIMACION" if aprobar else "RECHAZAR_ESTIMACION", "TIEMPO_ESTANDAR", p.tiempo_estandar_id, despues=resultado)
    return resultado


def revertir_tiempo_estandar(s: Session, te_id: int, usuario: str) -> dict:
    """Vuelve a la versión anterior de un tiempo estándar (aprendizaje reversible)."""
    te = s.get(TiempoEstandar, te_id)
    if te is None or not te.vigente:
        raise ValueError("Solo se puede revertir un tiempo estándar vigente")
    anterior = s.scalar(
        select(TiempoEstandar)
        .where(
            TiempoEstandar.seccion_codigo == te.seccion_codigo,
            TiempoEstandar.grupo_hf.is_(te.grupo_hf) if te.grupo_hf is None else TiempoEstandar.grupo_hf == te.grupo_hf,
            TiempoEstandar.tipo_operacion.is_(te.tipo_operacion) if te.tipo_operacion is None else TiempoEstandar.tipo_operacion == te.tipo_operacion,
            TiempoEstandar.version < te.version,
        )
        .order_by(TiempoEstandar.version.desc())
    )
    if anterior is None:
        raise ValueError("No hay versión anterior")
    te.vigente, anterior.vigente = False, True
    auditar(s, usuario, "REVERTIR_TIEMPO_ESTANDAR", "TIEMPO_ESTANDAR", te_id, despues={"reactivado": anterior.id})
    return {"reactivado": anterior.id}
