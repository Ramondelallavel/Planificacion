"""Servicio de planificación: une el motor (en memoria) con la base de datos.

Toda decisión automática queda registrada (plan, asignaciones con su explicación, cambios
ANTES/DESPUÉS/MOTIVO y auditoría). Las simulaciones se guardan como planes SIMULACION y
nunca modifican el plan oficial salvo aceptación explícita de un responsable.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from ..modelos import (
    Aparato,
    AsignacionPlan,
    Ausencia,
    CambioPlan,
    IncidenciaDatos,
    IncidenciaProduccion,
    Notificacion,
    Operacion,
    OrdenFabricacion,
    ParadaRecurso,
    Plan,
    Recurso,
    Tanda,
)
from ..modelos.enums import (
    EstadoIncidenciaDatos,
    EstadoOF,
    EstadoOperacion,
    EstadoPlan,
    EstadoProgramacion,
    Severidad,
    TipoPlan,
)
from ..servicios.auditoria import auditar
from .analisis import analizar_cuellos, calcular_kpis
from .calendario import repartir
from .modelo import AsigP, Instantanea, cargar_instantanea
from .programador import NoPlanificada, Programador, ResultadoProgramacion, _ventanas_combinadas, programar, tramos_json
from .replanificacion import Evento, replanificar
from .restricciones import validar_asignacion
from .riesgo import calcular_riesgos
from .simulacion import simular


class PlanBloqueado(Exception):
    def __init__(self, comprobaciones: list[dict]):
        super().__init__("Existen comprobaciones bloqueantes: no se puede generar un plan definitivo")
        self.comprobaciones = comprobaciones


class CambioRechazado(Exception):
    def __init__(self, errores: list[str]):
        super().__init__("; ".join(errores))
        self.errores = errores


# ------------------------------------------------------------------ utilidades de persistencia
def plan_activo(s: Session) -> Plan | None:
    return s.scalar(select(Plan).where(Plan.tipo == TipoPlan.OFICIAL, Plan.estado == EstadoPlan.ACTIVO).order_by(Plan.id.desc()))


def asignaciones_de(s: Session, plan: Plan) -> dict[int, AsigP]:
    salida = {}
    for a in s.scalars(select(AsignacionPlan).where(AsignacionPlan.plan_id == plan.id)):
        tramos = [(datetime.fromisoformat(x), datetime.fromisoformat(y)) for x, y in (a.segmentos or [[a.inicio.isoformat(), a.fin.isoformat()]])]
        salida[a.operacion_id] = AsigP(
            a.operacion_id, a.of_id, a.recurso_id, a.unidad, a.operario_id, a.inicio, a.fin, tramos, a.minutos, a.prioridad, a.explicacion, a.provisional, a.bloqueada
        )
    return salida


def no_planificadas_de(plan: Plan) -> dict[int, NoPlanificada]:
    return {n["operacion_id"]: NoPlanificada(n["operacion_id"], n["of_id"], n["of"], n["tipo"], n["motivo"], n["detalle"]) for n in (plan.no_planificadas or [])}


def _guardar_asignaciones(s: Session, plan: Plan, asigs: dict[int, AsigP], bloqueadas: set[int] | None = None) -> None:
    bloqueadas = bloqueadas or set()
    for a in asigs.values():
        s.add(
            AsignacionPlan(
                plan_id=plan.id,
                operacion_id=a.op_id,
                of_id=a.of_id,
                recurso_id=a.recurso_id,
                unidad=a.unidad,
                operario_id=a.operario_id,
                inicio=a.inicio,
                fin=a.fin,
                segmentos=tramos_json(a.tramos),
                minutos=a.minutos,
                prioridad=a.prioridad,
                bloqueada=a.op_id in bloqueadas,
                provisional=a.provisional,
                explicacion=a.explicacion,
            )
        )


def _json_riesgos(riesgos: dict) -> dict:
    return {
        "tandas": {str(k): v for k, v in riesgos["tandas"].items()},
        "aparatos": {str(k): v for k, v in riesgos["aparatos"].items()},
        "ofs": {str(k): v for k, v in riesgos["ofs"].items()},
    }


def _actualizar_entidades(s: Session, inst: Instantanea, asigs: dict[int, AsigP], riesgos: dict) -> None:
    """Refleja en OF, aparatos y tandas las fechas previstas y el riesgo del plan activo."""
    fechas: dict[int, list[datetime]] = {}
    for a in asigs.values():
        f = fechas.setdefault(a.of_id, [a.inicio, a.fin])
        f[0], f[1] = min(f[0], a.inicio), max(f[1], a.fin)
    for of_id in inst.of_ops:
        of = s.get(OrdenFabricacion, of_id)
        if of is None:
            continue
        r = riesgos["ofs"].get(of_id)
        if of_id in fechas:
            of.fecha_prevista_inicio, of.fecha_prevista_fin = fechas[of_id]
            if of.estado in (EstadoOF.NO_INICIADA, EstadoOF.LISTA):
                of.estado = EstadoOF.PLANIFICADA
        else:
            of.fecha_prevista_inicio = of.fecha_prevista_fin = None
        if r:
            of.riesgo_nivel = r["nivel"]
    for ap_id, r in riesgos["aparatos"].items():
        ap = s.get(Aparato, ap_id)
        if ap:
            ap.riesgo_nivel, ap.riesgo_motivos = r["nivel"], r["motivos"]
            ap.fin_previsto = datetime.fromisoformat(r["fin_previsto"]) if r["fin_previsto"] else None
            ap.carga_restante_h = r["horas_restantes"]
    for t_id, r in riesgos["tandas"].items():
        t = s.get(Tanda, t_id)
        if t:
            t.riesgo_nivel, t.riesgo_motivos = r["nivel"], r["motivos"]
            t.carga_restante_h = r["horas_restantes"]
            t.progreso = r["progreso"]
    for op_id in asigs:
        op = s.get(Operacion, op_id)
        if op and op.estado in (EstadoOperacion.PENDIENTE, EstadoOperacion.LISTA):
            op.estado = EstadoOperacion.PLANIFICADA


def _notificar(s: Session, inst: Instantanea, cambios: list[dict], titulo: str, lote: str) -> int:
    """Aviso a cada operario cuya carga cambia (antes o después)."""
    por_operario: dict[int, list[str]] = {}
    for c in cambios:
        for lado in ("antes", "despues"):
            foto = c.get(lado)
            if foto and foto.get("operario_id"):
                txt = f"OF {c['of']} ({c['tipo']}): " + (
                    f"{_hhmm(c['antes'])} → {_hhmm(c['despues'])}"
                    if c.get("antes") and c.get("despues")
                    else ("retirada de tu plan" if not c.get("despues") else f"nueva a las {_hhmm(c['despues'])}")
                )
                por_operario.setdefault(foto["operario_id"], [])
                if txt not in por_operario[foto["operario_id"]]:
                    por_operario[foto["operario_id"]].append(txt)
    for oid, lineas in por_operario.items():
        s.add(Notificacion(operario_id=oid, titulo=titulo, mensaje="\n".join(lineas[:20]), nivel="AVISO", referencia=lote))
    return len(por_operario)


def _hhmm(foto: dict | None) -> str:
    if not foto:
        return "—"
    d = datetime.fromisoformat(foto["inicio"])
    return f"{d:%d/%m %H:%M} en {foto.get('recurso') or '?'}"


def recalcular_plan(s: Session, plan: Plan, ahora: datetime) -> Instantanea:
    """Recalcula riesgos, cuellos y KPIs de un plan ya guardado (sin mover nada)."""
    inst = cargar_instantanea(s, ahora, incluir_bloqueadas_plan=False)
    asigs = {k: v for k, v in asignaciones_de(s, plan).items() if k in inst.ops}
    no_plan = {k: v for k, v in no_planificadas_de(plan).items() if k in inst.ops and k not in asigs}
    res = ResultadoProgramacion(asigs, no_plan, Programador(inst).prioridades)
    riesgos = calcular_riesgos(inst, res)
    cuellos = analizar_cuellos(inst, res)
    plan.kpis = calcular_kpis(inst, res, riesgos, cuellos)
    plan.riesgos = {**_json_riesgos(riesgos), "cuellos": cuellos}
    _actualizar_entidades(s, inst, asigs, riesgos)
    return inst


# ------------------------------------------------------------------ comprobaciones previas
def comprobaciones_previas(s: Session, inst: Instantanea) -> list[dict]:
    salida: list[dict] = []
    docs = {d for (d,) in s.execute(select(OrdenFabricacion.documento_id).where(OrdenFabricacion.id.in_(list(inst.of_ops))).distinct()) if d}
    criticas = (
        s.scalars(
            select(IncidenciaDatos).where(
                IncidenciaDatos.documento_id.in_(docs), IncidenciaDatos.severidad == Severidad.CRITICA, IncidenciaDatos.estado == EstadoIncidenciaDatos.ABIERTA
            )
        ).all()
        if docs
        else []
    )
    errores = (
        s.scalar(
            select(func.count(IncidenciaDatos.id)).where(
                IncidenciaDatos.documento_id.in_(docs), IncidenciaDatos.severidad == Severidad.ERROR, IncidenciaDatos.estado == EstadoIncidenciaDatos.ABIERTA
            )
        )
        if docs
        else 0
    )
    salida.append(
        {
            "paso": "1. Validar datos",
            "estado": "BLOQUEANTE" if criticas else ("AVISO" if errores else "OK"),
            "detalle": (f"{len(criticas)} errores críticos de integridad sin resolver: " + "; ".join(c.mensaje[:120] for c in criticas[:3]))
            if criticas
            else (f"{errores} errores de datos abiertos (revisar)" if errores else "Sin errores críticos de integridad"),
        }
    )
    prog = Programador(inst)
    sin_rec = [op for op in inst.ops.values() if not prog.rec_op.get(op.id)]
    salida.append(
        {
            "paso": "2. Comprobar recursos",
            "estado": "AVISO" if sin_rec else "OK",
            "detalle": f"{len(sin_rec)} operaciones sin recurso capaz" if sin_rec else f"{len(inst.recursos)} recursos activos; todas las operaciones tienen recurso",
        }
    )
    sin_op = [
        op
        for op in inst.ops.values()
        if prog.rec_op.get(op.id)
        and all(inst.recursos[r].requiere_operario for r in prog.rec_op[op.id])
        and not any(o.cualificado(inst.recursos[r], op) for r in prog.rec_op[op.id] for o in inst.operarios.values())
    ]
    ausentes = [o for o in inst.operarios.values() if any(a <= inst.ahora < b for a, b in o.ausencias)]
    salida.append(
        {
            "paso": "3. Comprobar trabajadores",
            "estado": "AVISO" if sin_op else "OK",
            "detalle": (f"{len(sin_op)} operaciones sin operario cualificado. " if sin_op else "Todas las operaciones tienen operario cualificado. ")
            + f"{len(inst.operarios)} operarios activos, {len(ausentes)} ausentes ahora.",
        }
    )
    ciclos = (
        s.scalar(
            select(func.count(IncidenciaDatos.id)).where(
                IncidenciaDatos.tipo == "DEPENDENCIA_CIRCULAR", IncidenciaDatos.estado == EstadoIncidenciaDatos.ABIERTA, IncidenciaDatos.documento_id.in_(docs)
            )
        )
        if docs
        else 0
    )
    externas = sorted({n for op in inst.ops.values() for n in op.bloqueos_externos})
    salida.append(
        {
            "paso": "4. Comprobar dependencias",
            "estado": "BLOQUEANTE" if ciclos else ("AVISO" if externas else "OK"),
            "detalle": (f"{ciclos} dependencias circulares. " if ciclos else "Sin dependencias circulares. ")
            + (f"Predecesoras fuera del plan sin fecha: {', '.join(externas[:10])}" if externas else ""),
        }
    )
    sin_material = sorted({op.of_numero for op in inst.ops.values() if op.material_bloqueado})
    salida.append(
        {
            "paso": "5. Comprobar materiales",
            "estado": "AVISO" if sin_material else "OK",
            "detalle": f"OF sin material ni fecha: {', '.join(sin_material[:10])}"
            if sin_material
            else "Sin faltas de material registradas (la disponibilidad de material procede de MRP cuando esté integrado)",
        }
    )
    pend = sorted({op.of_numero for op in inst.ops.values() if op.pendiente_programa})
    salida.append(
        {
            "paso": "6. Comprobar programación",
            "estado": "AVISO" if pend else "OK",
            "detalle": f"{len(pend)} OF pendientes de programación (se planifican de forma provisional tras su programación)" if pend else "Sin OF pendientes de programación",
        }
    )
    averiados = [r.codigo for r in inst.recursos.values() if r.paradas and any(a <= inst.ahora < b for a, b in r.paradas)]
    sin_dur = [op for op in inst.ops.values() if op.duracion is None]
    salida.append(
        {
            "paso": "7. Detectar conflictos",
            "estado": "AVISO" if (averiados or sin_dur) else "OK",
            "detalle": (f"Recursos parados ahora: {', '.join(averiados)}. " if averiados else "")
            + (f"{len(sin_dur)} operaciones sin duración (DATO NO DISPONIBLE)." if sin_dur else "Sin conflictos"),
        }
    )
    return salida


# ------------------------------------------------------------------ generación
def generar_plan(
    s: Session, usuario: str, ahora: datetime, nombre: str | None = None, definitivo: bool = False, tanda_ids: list[int] | None = None, motivo: str | None = None
) -> dict:
    inst = cargar_instantanea(s, ahora, tanda_ids)
    checks = comprobaciones_previas(s, inst)
    if definitivo and any(c["estado"] == "BLOQUEANTE" for c in checks):
        raise PlanBloqueado(checks)
    res = programar(inst)
    riesgos = calcular_riesgos(inst, res)
    cuellos = analizar_cuellos(inst, res)
    kpis = calcular_kpis(inst, res, riesgos, cuellos)
    anterior = plan_activo(s)
    bloqueadas_prev: set[int] = set()
    if anterior:
        bloqueadas_prev = {a.operacion_id for a in s.scalars(select(AsignacionPlan).where(AsignacionPlan.plan_id == anterior.id, AsignacionPlan.bloqueada.is_(True)))}
        anterior.estado = EstadoPlan.ARCHIVADO
    plan = Plan(
        nombre=nombre or f"Plan {ahora:%d/%m/%Y %H:%M}",
        tipo=TipoPlan.OFICIAL,
        estado=EstadoPlan.ACTIVO,
        creado_por=usuario,
        ahora_referencia=ahora,
        horizonte_fin=inst.horizonte,
        configuracion={k: inst.config[k] for k in ("pesos_prioridad", "objetivos_plan", "umbrales_riesgo", "planificacion", "semana_fabricacion")},
        kpis=kpis,
        riesgos={**_json_riesgos(riesgos), "cuellos": cuellos},
        no_planificadas=[n.a_dict() for n in res.no_planificadas.values()],
        comprobaciones=checks,
        plan_base_id=anterior.id if anterior else None,
        motivo=motivo,
        definitivo=definitivo,
    )
    s.add(plan)
    s.flush()
    _guardar_asignaciones(s, plan, res.asignaciones, bloqueadas_prev & set(res.asignaciones))
    _actualizar_entidades(s, inst, res.asignaciones, riesgos)
    lote = uuid.uuid4().hex[:12]
    s.add(
        CambioPlan(
            plan_id=plan.id,
            lote=lote,
            usuario=usuario,
            tipo="GENERACION",
            motivo=motivo or "Generación de plan",
            despues={"planificadas": kpis["planificadas"], "no_planificadas": kpis["no_planificadas"]},
        )
    )
    auditar(
        s,
        usuario,
        "GENERAR_PLAN",
        "PLAN",
        plan.id,
        despues={"kpis": {k: v for k, v in kpis.items() if k != "carga_por_recurso"}, "definitivo": definitivo},
        motivo=motivo,
        automatica=False,
    )
    return {"plan_id": plan.id, "kpis": kpis, "comprobaciones": checks, "no_planificadas": len(res.no_planificadas), "riesgo_tandas": list(riesgos["tandas"].values())}


# ------------------------------------------------------------------ incidencias y replanificación
def _evento_desde(datos: dict, ahora: datetime) -> Evento:
    def f(clave: str) -> datetime | None:
        v = datos.get(clave)
        return datetime.fromisoformat(v) if isinstance(v, str) and v else v

    ini = f("inicio") or ahora
    fin = f("fin")
    if fin is None and datos.get("horas"):
        fin = ini + timedelta(hours=float(datos["horas"]))
    return Evento(
        tipo=datos["tipo"],
        descripcion=datos.get("descripcion") or datos["tipo"],
        recurso_id=datos.get("recurso_id"),
        operario_id=datos.get("operario_id"),
        of_id=datos.get("of_id"),
        op_id=datos.get("operacion_id"),
        inicio=ini,
        fin=fin,
        minutos_extra=datos.get("minutos_extra"),
        material_desde=f("material_desde"),
        prioridad=datos.get("prioridad"),
    )


def _persistir_replan(s: Session, plan: Plan, inst: Instantanea, rep, usuario: str, tipo: str, motivo: str) -> str:
    lote = uuid.uuid4().hex[:12]
    bloqueadas = {a.operacion_id for a in s.scalars(select(AsignacionPlan).where(AsignacionPlan.plan_id == plan.id, AsignacionPlan.bloqueada.is_(True)))}
    s.execute(delete(AsignacionPlan).where(AsignacionPlan.plan_id == plan.id))
    _guardar_asignaciones(s, plan, rep.asignaciones, bloqueadas & set(rep.asignaciones))
    riesgos = rep.riesgos_despues
    cuellos = analizar_cuellos(inst, rep.resultado)
    plan.kpis = calcular_kpis(inst, rep.resultado, riesgos, cuellos)
    plan.riesgos = {**_json_riesgos(riesgos), "cuellos": cuellos}
    plan.no_planificadas = [n.a_dict() for n in rep.resultado.no_planificadas.values()]
    for c in rep.cambios:
        tanda_antes = tanda_despues = None
        op = inst.ops.get(c["operacion_id"])
        if op and op.tanda_id in rep.riesgos_antes["tandas"]:
            tanda_antes = rep.riesgos_antes["tandas"][op.tanda_id]["nivel"]
            tanda_despues = riesgos["tandas"].get(op.tanda_id, {}).get("nivel")
        s.add(
            CambioPlan(
                plan_id=plan.id,
                lote=lote,
                usuario=usuario,
                tipo=tipo,
                operacion_id=c["operacion_id"],
                of_numero=c["of"],
                antes=c["antes"],
                despues=c["despues"],
                impacto_min=c["impacto_min"],
                motivo=c["motivo"],
                riesgo_antes=tanda_antes,
                riesgo_despues=tanda_despues,
            )
        )
    _actualizar_entidades(s, inst, rep.asignaciones, riesgos)
    _notificar(s, inst, rep.cambios, f"Cambio de plan: {motivo[:120]}", lote)
    return lote


def registrar_incidencia(s: Session, datos: dict, usuario: str, ahora: datetime) -> dict:
    """Registra la incidencia, aplica su efecto en la BD y replanifica solo la zona afectada."""
    ev = _evento_desde(datos, ahora)
    inc = IncidenciaProduccion(
        tipo=ev.tipo,
        descripcion=ev.descripcion,
        recurso_id=ev.recurso_id,
        operario_id=ev.operario_id,
        of_id=ev.of_id,
        operacion_id=ev.op_id,
        inicio=ev.inicio,
        fin_prevista=ev.fin,
        reportado_por=usuario,
        severidad=datos.get("severidad", "MEDIA"),
    )
    s.add(inc)
    s.flush()
    plan = plan_activo(s)
    resultado: dict = {"incidencia_id": inc.id, "replanificado": False}
    rep = None
    inst = None
    if plan is not None:
        inst = cargar_instantanea(s, ahora)
        rep = replanificar(inst, asignaciones_de(s, plan), ev, no_plan_antes=no_planificadas_de(plan))
    # efecto persistente del evento
    if ev.tipo == "AVERIA" and ev.recurso_id:
        s.add(ParadaRecurso(recurso_id=ev.recurso_id, inicio=ev.inicio, fin=ev.fin, motivo=ev.descripcion, incidencia_id=inc.id))
        r = s.get(Recurso, ev.recurso_id)
        if r and ev.inicio <= ahora and (ev.fin is None or ev.fin > ahora):
            r.estado = "AVERIADO"
    elif ev.tipo == "AUSENCIA" and ev.operario_id:
        s.add(Ausencia(operario_id=ev.operario_id, inicio=ev.inicio, fin=ev.fin, motivo=ev.descripcion, incidencia_id=inc.id))
    elif ev.tipo == "FALTA_MATERIAL" and ev.of_id:
        of = s.get(OrdenFabricacion, ev.of_id)
        if of:
            of.material_disponible = False if ev.material_desde is None else None
            of.material_disponible_desde = ev.material_desde
            of.estado = EstadoOF.ESPERANDO_MATERIAL
    elif ev.tipo in ("OF_URGENTE", "CAMBIO_PRIORIDAD") and ev.of_id:
        of = s.get(OrdenFabricacion, ev.of_id)
        if of:
            of.urgente = of.urgente or ev.tipo == "OF_URGENTE"
            if ev.prioridad is not None:
                of.prioridad_ortems = ev.prioridad
    elif ev.tipo in ("RETRASO", "OPERACION_LENTA") and ev.op_id:
        op = s.get(Operacion, ev.op_id)
        if op and op.duracion_estimada_min is not None:
            op.duracion_estimada_min += float(ev.minutos_extra or 0)
            op.origen_duracion = (op.origen_duracion or "") + f" | +{ev.minutos_extra} min por incidencia #{inc.id}"
    if plan is not None and rep is not None and inst is not None:
        from .replanificacion import aplicar_evento

        inst2 = inst.copia()
        aplicar_evento(inst2, ev)
        lote = _persistir_replan(s, plan, inst2, rep, usuario, "REPLANIFICACION", ev.descripcion)
        inc.lote_replanificacion = lote
        inc.impacto = {"resumen": rep.resumen, "cambios": len(rep.cambios)}
        resultado.update(replanificado=True, lote=lote, **_resultado_replan(rep))
    auditar(s, usuario, "INCIDENCIA", "INCIDENCIA", inc.id, despues={"tipo": ev.tipo, "descripcion": ev.descripcion, "replanificado": resultado["replanificado"]})
    return resultado


def _resultado_replan(rep) -> dict:
    tandas = []
    for t_id, d in rep.riesgos_despues["tandas"].items():
        a = rep.riesgos_antes["tandas"].get(t_id, {})
        tandas.append(
            {
                "tanda": d["numero"],
                "riesgo_antes": a.get("nivel"),
                "riesgo_despues": d["nivel"],
                "fin_antes": a.get("fin_previsto"),
                "fin_despues": d["fin_previsto"],
                "motivos": d["motivos"][:3],
            }
        )
    return {"resumen": rep.resumen, "cambios": rep.cambios, "tandas": tandas, "afectadas": len(rep.afectadas), "sale_del_plan": rep.nuevas_no_planificadas}


# ------------------------------------------------------------------ OF urgente: simular → aceptar / rechazar
def simular_of_urgente(s: Session, of_id: int, usuario: str, ahora: datetime, motivo: str | None = None) -> dict:
    plan = plan_activo(s)
    if plan is None:
        raise ValueError("No hay plan activo: genere un plan antes de introducir una OF urgente")
    of = s.get(OrdenFabricacion, of_id)
    if of is None:
        raise ValueError("OF inexistente")
    inst = cargar_instantanea(s, ahora)
    if not inst.of_ops.get(of_id):
        raise ValueError(f"La OF {of.numero} no tiene operaciones pendientes en las tandas planificadas")
    ev = Evento("OF_URGENTE", motivo or f"OF {of.numero} urgente", of_id=of_id)
    rep = replanificar(inst, asignaciones_de(s, plan), ev, no_plan_antes=no_planificadas_de(plan))
    sim = Plan(
        nombre=f"Simulación OF urgente {of.numero}",
        tipo=TipoPlan.SIMULACION,
        estado=EstadoPlan.BORRADOR,
        creado_por=usuario,
        ahora_referencia=ahora,
        horizonte_fin=inst.horizonte,
        plan_base_id=plan.id,
        escenario={"tipo": "OF_URGENTE", "of_id": of_id, "of": of.numero, "motivo": motivo},
        kpis=None,
        riesgos=_json_riesgos(rep.riesgos_despues),
        no_planificadas=[n.a_dict() for n in rep.resultado.no_planificadas.values()],
        motivo=rep.resumen,
    )
    s.add(sim)
    s.flush()
    _guardar_asignaciones(s, sim, rep.asignaciones)
    lote = uuid.uuid4().hex[:12]
    for c in rep.cambios:
        s.add(
            CambioPlan(
                plan_id=sim.id,
                lote=lote,
                usuario=usuario,
                tipo="OF_URGENTE",
                operacion_id=c["operacion_id"],
                of_numero=c["of"],
                antes=c["antes"],
                despues=c["despues"],
                impacto_min=c["impacto_min"],
                motivo=c["motivo"],
            )
        )
    auditar(s, usuario, "SIMULAR_OF_URGENTE", "PLAN", sim.id, despues={"of": of.numero, "resumen": rep.resumen})
    r = _resultado_replan(rep)
    desplazadas = [c for c in rep.cambios if c["of_id"] != of_id and c["impacto_min"] and c["impacto_min"] > 0]
    urgentes = [c for c in rep.cambios if c["of_id"] == of_id]
    frases = [f"desplazar OF {c['of']} {c['impacto_min']:.0f} min" for c in sorted(desplazadas, key=lambda c: -c["impacto_min"])[:10]]
    frases += [f"riesgo TANDA {t['tanda']}: {t['riesgo_antes']} → {t['riesgo_despues']}" for t in r["tandas"] if t["riesgo_antes"] != t["riesgo_despues"]]
    return {
        "simulacion_id": sim.id,
        "of": of.numero,
        "texto": "Introducir esta OF ahora provocaría: " + ("; ".join(frases) if frases else "ningún desplazamiento relevante."),
        "of_urgente_planificada": [{"inicio": c["despues"]["inicio"], "fin": c["despues"]["fin"], "recurso": c["despues"]["recurso"]} for c in urgentes if c["despues"]],
        **r,
    }


def decidir_simulacion(s: Session, sim_id: int, aceptar: bool, usuario: str, motivo: str | None = None) -> dict:
    sim = s.get(Plan, sim_id)
    if sim is None or sim.tipo != TipoPlan.SIMULACION or sim.estado != EstadoPlan.BORRADOR:
        raise ValueError("Simulación inexistente o ya decidida")
    base = s.get(Plan, sim.plan_base_id) if sim.plan_base_id else None
    if not aceptar:
        sim.estado = EstadoPlan.DESCARTADO
        auditar(s, usuario, "RECHAZAR_SIMULACION", "PLAN", sim.id, despues=sim.escenario, motivo=motivo)
        return {"aceptada": False, "simulacion_id": sim.id}
    activo = plan_activo(s)
    if base is None or activo is None or activo.id != base.id:
        raise ValueError("El plan ha cambiado desde que se hizo la simulación: vuelva a simular")
    nuevo = Plan(
        nombre=f"{base.nombre} + {sim.nombre}",
        tipo=TipoPlan.OFICIAL,
        estado=EstadoPlan.ACTIVO,
        creado_por=usuario,
        ahora_referencia=sim.ahora_referencia,
        horizonte_fin=sim.horizonte_fin,
        configuracion=base.configuracion,
        riesgos=sim.riesgos,
        no_planificadas=sim.no_planificadas,
        comprobaciones=base.comprobaciones,
        plan_base_id=base.id,
        motivo=f"Aceptada simulación {sim.id}: {sim.motivo}",
        kpis=base.kpis,
    )
    base.estado = EstadoPlan.ARCHIVADO
    s.add(nuevo)
    s.flush()
    bloqueadas = {a.operacion_id for a in s.scalars(select(AsignacionPlan).where(AsignacionPlan.plan_id == base.id, AsignacionPlan.bloqueada.is_(True)))}
    for a in s.scalars(select(AsignacionPlan).where(AsignacionPlan.plan_id == sim.id)):
        s.add(
            AsignacionPlan(
                **{
                    c: getattr(a, c)
                    for c in ("operacion_id", "of_id", "recurso_id", "unidad", "operario_id", "inicio", "fin", "segmentos", "minutos", "prioridad", "provisional", "explicacion")
                },
                plan_id=nuevo.id,
                bloqueada=a.operacion_id in bloqueadas,
            )
        )
    cambios = list(s.scalars(select(CambioPlan).where(CambioPlan.plan_id == sim.id)))
    lote = uuid.uuid4().hex[:12]
    for c in cambios:
        s.add(
            CambioPlan(
                plan_id=nuevo.id,
                lote=lote,
                usuario=usuario,
                tipo=c.tipo,
                operacion_id=c.operacion_id,
                of_numero=c.of_numero,
                antes=c.antes,
                despues=c.despues,
                impacto_min=c.impacto_min,
                motivo=c.motivo,
            )
        )
    esc = sim.escenario or {}
    if esc.get("tipo") == "OF_URGENTE":
        of = s.get(OrdenFabricacion, esc["of_id"])
        if of:
            of.urgente = True
    sim.estado = EstadoPlan.ARCHIVADO
    s.flush()
    inst = recalcular_plan(s, nuevo, sim.ahora_referencia)
    _notificar(s, inst, [{"of": c.of_numero, "tipo": "", "antes": c.antes, "despues": c.despues} for c in cambios], f"Cambio de plan: {sim.nombre}", lote)
    auditar(s, usuario, "ACEPTAR_SIMULACION", "PLAN", nuevo.id, antes={"plan": base.id}, despues={"simulacion": sim.id, "escenario": esc}, motivo=motivo)
    return {"aceptada": True, "plan_id": nuevo.id}


# ------------------------------------------------------------------ cambios manuales
def mover_asignacion(
    s: Session,
    operacion_id: int,
    usuario: str,
    ahora: datetime,
    inicio: datetime | None = None,
    recurso_id: int | None = None,
    operario_id: int | None = None,
    motivo: str | None = None,
    bloquear: bool | None = None,
) -> dict:
    plan = plan_activo(s)
    if plan is None:
        raise ValueError("No hay plan activo")
    fila = s.scalar(select(AsignacionPlan).where(AsignacionPlan.plan_id == plan.id, AsignacionPlan.operacion_id == operacion_id))
    if fila is None:
        raise ValueError("La operación no está en el plan activo")
    inst = cargar_instantanea(s, ahora, incluir_bloqueadas_plan=False)
    plan_mem = asignaciones_de(s, plan)
    actual = plan_mem[operacion_id]
    op = inst.ops.get(operacion_id)
    pedido = {"inicio": inicio.isoformat() if inicio else None, "recurso_id": recurso_id, "operario_id": operario_id}

    def rechazar(errores: list[str]) -> None:
        # todo intento rechazado queda auditado (quién, qué pidió y por qué no es posible)
        auditar(s, usuario, "CAMBIO_MANUAL_RECHAZADO", "ASIGNACION", operacion_id, antes=_foto(inst, actual), despues=pedido, motivo="; ".join(errores))
        raise CambioRechazado(errores)

    if op is None:
        rechazar(["La operación ya no está pendiente"])
    nuevo_rec = recurso_id if recurso_id is not None else actual.recurso_id
    r = inst.recursos.get(nuevo_rec)
    if r is None:
        rechazar(["Recurso inexistente o inactivo"])
    nuevo_op = operario_id if operario_id is not None else actual.operario_id
    o = inst.operarios.get(nuevo_op) if (nuevo_op is not None and r.requiere_operario) else None
    if r.requiere_operario and o is None:
        rechazar([f"{r.codigo} necesita un operario válido"])
    vent = _ventanas_combinadas(inst, r, o)
    ini = inicio or actual.inicio
    minutos = max(0.0, (op.duracion or actual.minutos) - op.minutos_hechos)
    tramos = repartir(vent, ini, minutos)
    if tramos is None:
        rechazar(["No hay ventana laborable suficiente en el horizonte para ese inicio"])
    if tramos[0][0] != ini:
        # el inicio pedido cae fuera de turno: se informa en lugar de moverlo en silencio
        rechazar([f"{ini:%d/%m %H:%M} está fuera de turno para {r.codigo}{' / ' + o.codigo if o else ''}; primer inicio posible: {tramos[0][0]:%d/%m %H:%M}"])
    candidata = AsigP(
        operacion_id,
        actual.of_id,
        r.id,
        actual.unidad if r.id == actual.recurso_id else 0,
        o.id if o else None,
        tramos[0][0],
        tramos[-1][1],
        tramos,
        minutos,
        actual.prioridad,
        actual.explicacion,
        actual.provisional,
    )
    errores, avisos = validar_asignacion(inst, candidata, {k: v for k, v in plan_mem.items() if k != operacion_id})
    if errores:
        pedido.update(_foto(inst, candidata))
        rechazar(errores)
    expl = dict(actual.explicacion or {})
    expl["cambio_manual"] = {"usuario": usuario, "motivo": motivo, "fecha": ahora.isoformat()}
    candidata.explicacion = expl
    # la operación movida queda fija; se recolocan solo las sucesoras que dejarían de cumplir la precedencia
    plan_mem[operacion_id] = AsigP(**{**candidata.__dict__, "fija": True})
    ev = Evento("MANUAL", motivo or f"Cambio manual de {usuario}")
    from .replanificacion import _diff

    afectadas: set[int] = set()
    pila = [operacion_id]
    while pila:
        k = pila.pop()
        fin_k = plan_mem[k].fin if k in plan_mem else None
        for sid in inst.sucesoras_op(k):
            if sid in plan_mem and sid not in afectadas and fin_k and plan_mem[sid].inicio < fin_k:
                afectadas.add(sid)
                pila.append(sid)
    antes_plan = asignaciones_de(s, plan)
    if afectadas:
        fijas = [AsigP(**{**a.__dict__, "fija": True}) for i, a in plan_mem.items() if i not in afectadas and i in inst.ops]
        res = Programador(inst).ejecutar(afectadas, fijas)
        nuevo = {i: (plan_mem[i] if i not in afectadas else a) for i, a in res.asignaciones.items()}
        no_plan = res.no_planificadas
    else:
        nuevo = {i: a for i, a in plan_mem.items() if i in inst.ops}
        no_plan = {}
    cambios = _diff(inst, {k: v for k, v in antes_plan.items() if k in inst.ops}, nuevo, ev.descripcion, no_plan)
    bloqueadas = {a.operacion_id for a in s.scalars(select(AsignacionPlan).where(AsignacionPlan.plan_id == plan.id, AsignacionPlan.bloqueada.is_(True)))}
    if bloquear is True:
        bloqueadas.add(operacion_id)
    elif bloquear is False:
        bloqueadas.discard(operacion_id)
    s.execute(delete(AsignacionPlan).where(AsignacionPlan.plan_id == plan.id))
    _guardar_asignaciones(s, plan, nuevo, bloqueadas & set(nuevo))
    res_total = ResultadoProgramacion(nuevo, {**no_planificadas_de(plan), **no_plan}, Programador(inst).prioridades)
    riesgos = calcular_riesgos(inst, res_total)
    plan.riesgos = {**_json_riesgos(riesgos), "cuellos": analizar_cuellos(inst, res_total)}
    lote = uuid.uuid4().hex[:12]
    for c in cambios:
        s.add(
            CambioPlan(
                plan_id=plan.id,
                lote=lote,
                usuario=usuario,
                tipo="MANUAL",
                operacion_id=c["operacion_id"],
                of_numero=c["of"],
                antes=c["antes"],
                despues=c["despues"],
                impacto_min=c["impacto_min"],
                motivo=c["motivo"],
            )
        )
    _actualizar_entidades(s, inst, nuevo, riesgos)
    _notificar(s, inst, cambios, f"Cambio manual del plan ({usuario})", lote)
    auditar(s, usuario, "CAMBIO_MANUAL_PLAN", "ASIGNACION", operacion_id, antes=_foto(inst, actual), despues=_foto(inst, candidata), motivo=motivo)
    return {"aceptado": True, "avisos": avisos, "cambios": cambios, "lote": lote}


def _foto(inst: Instantanea, a: AsigP) -> dict:
    return {
        "inicio": a.inicio.isoformat(),
        "fin": a.fin.isoformat(),
        "recurso": inst.recursos[a.recurso_id].codigo if a.recurso_id in inst.recursos else None,
        "operario": inst.operarios[a.operario_id].codigo if a.operario_id in inst.operarios else None,
    }


def bloquear(s: Session, operacion_id: int, bloqueada: bool, usuario: str, motivo: str | None = None) -> None:
    plan = plan_activo(s)
    fila = s.scalar(select(AsignacionPlan).where(AsignacionPlan.plan_id == plan.id, AsignacionPlan.operacion_id == operacion_id)) if plan else None
    if fila is None:
        raise ValueError("La operación no está en el plan activo")
    fila.bloqueada = bloqueada
    auditar(s, usuario, "BLOQUEAR_ASIGNACION" if bloqueada else "DESBLOQUEAR_ASIGNACION", "ASIGNACION", operacion_id, motivo=motivo)


# ------------------------------------------------------------------ what-if
def simular_escenario(s: Session, escenario: dict, usuario: str, ahora: datetime, guardar: bool = True) -> dict:
    plan = plan_activo(s)
    tandas = escenario.get("incluir_tandas")
    inst = cargar_instantanea(s, ahora, (list({*s.scalars(select(Tanda.id).where(Tanda.estado == "ACTIVA", Tanda.incluida_en_plan.is_(True))), *tandas}) if tandas else None))
    base = asignaciones_de(s, plan) if plan else None
    if base is not None:
        base = {k: v for k, v in base.items() if k in inst.ops}
    r = simular(inst, base, escenario, no_planificadas_de(plan) if plan else None)
    res: ResultadoProgramacion = r.pop("resultado")
    r.pop("instantanea")
    if guardar:
        sim = Plan(
            nombre=escenario.get("nombre") or "Simulación what-if",
            tipo=TipoPlan.SIMULACION,
            estado=EstadoPlan.BORRADOR,
            creado_por=usuario,
            ahora_referencia=ahora,
            plan_base_id=plan.id if plan else None,
            escenario=escenario,
            kpis=r["kpis_simulado"],
            no_planificadas=[n.a_dict() for n in res.no_planificadas.values()],
            motivo="; ".join(r["escenario"]),
        )
        s.add(sim)
        s.flush()
        _guardar_asignaciones(s, sim, res.asignaciones)
        r["simulacion_id"] = sim.id
        auditar(s, usuario, "SIMULACION", "PLAN", sim.id, despues={"escenario": r["escenario"]})
    return r


# ------------------------------------------------------------------ programación LCH / LaserTub
def registrar_programa(s: Session, of_id: int, codigo: str, usuario: str, recurso_codigo: str | None = None, notas: str | None = None) -> dict:
    from ..modelos import ProgramaCNC

    of = s.get(OrdenFabricacion, of_id)
    if of is None:
        raise ValueError("OF inexistente")
    s.add(ProgramaCNC(codigo=codigo, of_id=of_id, recurso_codigo=recurso_codigo, fuente="USUARIO", registrado_por=usuario, notas=notas))
    antes = of.estado_programacion
    of.estado_programacion = EstadoProgramacion.LISTA_PARA_FABRICAR
    if of.estado == EstadoOF.ESPERANDO_PROGRAMACION:
        of.estado = EstadoOF.LISTA
    for op in of.operaciones:
        if op.tipo == "PROGRAMACION" and op.estado not in (EstadoOperacion.TERMINADA,):
            op.estado = EstadoOperacion.TERMINADA
            op.duracion_real_min = op.duracion_real_min or 0
        elif op.estado == EstadoOperacion.PENDIENTE_PROGRAMACION:
            op.estado = EstadoOperacion.LISTA
    plan = plan_activo(s)
    if plan:
        for a in s.scalars(select(AsignacionPlan).where(AsignacionPlan.plan_id == plan.id, AsignacionPlan.of_id == of_id)):
            a.provisional = False
    auditar(s, usuario, "REGISTRAR_PROGRAMA", "OF", of.numero, antes={"estado_programacion": antes}, despues={"programa": codigo, "estado_programacion": of.estado_programacion})
    return {"of": of.numero, "estado_programacion": of.estado_programacion}


def informar_disponibilidad(s: Session, of_id: int, fecha: datetime | None, fuente: str, usuario: str, motivo: str | None = None) -> None:
    of = s.get(OrdenFabricacion, of_id)
    if of is None:
        raise ValueError("OF inexistente")
    antes = of.disponible_prevista.isoformat() if of.disponible_prevista else None
    of.disponible_prevista = fecha
    of.fuente_disponible = fuente
    auditar(
        s,
        usuario,
        "DISPONIBILIDAD_OF_EXTERNA",
        "OF",
        of.numero,
        antes={"disponible_prevista": antes},
        despues={"disponible_prevista": fecha.isoformat() if fecha else None, "fuente": fuente},
        motivo=motivo,
    )


def resumen_plan(s: Session) -> dict | None:
    plan = plan_activo(s)
    if plan is None:
        return None
    return {
        "plan_id": plan.id,
        "nombre": plan.nombre,
        "creado": plan.creado.isoformat(),
        "creado_por": plan.creado_por,
        "ahora_referencia": plan.ahora_referencia.isoformat(),
        "kpis": plan.kpis,
        "comprobaciones": plan.comprobaciones,
        "definitivo": plan.definitivo,
    }


def documentos_con_criticos(s: Session) -> list[int]:
    return [
        d
        for (d,) in s.execute(
            select(IncidenciaDatos.documento_id).where(IncidenciaDatos.severidad == Severidad.CRITICA, IncidenciaDatos.estado == EstadoIncidenciaDatos.ABIERTA).distinct()
        )
    ]


__all__ = [
    "CambioRechazado",
    "PlanBloqueado",
    "asignaciones_de",
    "bloquear",
    "comprobaciones_previas",
    "decidir_simulacion",
    "generar_plan",
    "informar_disponibilidad",
    "mover_asignacion",
    "plan_activo",
    "registrar_incidencia",
    "registrar_programa",
    "recalcular_plan",
    "resumen_plan",
    "simular_escenario",
    "simular_of_urgente",
]
