"""Plan de producción: generación, Gantt, plan por turno, cambios, simulaciones y OF urgentes."""

from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from ... import configuracion
from ...modelos import Aparato, AsignacionPlan, CambioPlan, DependenciaOF, Festivo, JornadaExtra, Operacion, Operario, OrdenFabricacion, Plan, Recurso, Tanda, Turno
from ...modelos.enums import TipoPlan
from ...planificacion import servicio as sv
from ...planificacion.calendario import turno_desde_modelo, ventanas_turno
from ...planificacion.modelo import cargar_instantanea, limite_semana
from ..deps import UsuarioActual, ahora, get_sesion, requiere

router = APIRouter(prefix="/plan", tags=["plan"])


class Generar(BaseModel):
    nombre: str | None = None
    definitivo: bool = False
    tanda_ids: list[int] | None = None
    motivo: str | None = None


@router.post("/comprobaciones")
def comprobaciones(s: Session = Depends(get_sesion), _: UsuarioActual = Depends(requiere("ver"))) -> list[dict]:
    return sv.comprobaciones_previas(s, cargar_instantanea(s, ahora()))


@router.post("/generar")
def generar(datos: Generar, s: Session = Depends(get_sesion), u: UsuarioActual = Depends(requiere("planificar"))) -> dict:
    return sv.generar_plan(s, u.usuario, ahora(), datos.nombre, datos.definitivo, datos.tanda_ids, datos.motivo)


@router.get("/activo")
def activo(s: Session = Depends(get_sesion), _: UsuarioActual = Depends(requiere("ver"))) -> dict:
    r = sv.resumen_plan(s)
    if r is None:
        return {"plan_id": None}
    plan = sv.plan_activo(s)
    r["cuellos"] = (plan.riesgos or {}).get("cuellos", [])
    r["tandas"] = list((plan.riesgos or {}).get("tandas", {}).values())
    r["aparatos"] = list((plan.riesgos or {}).get("aparatos", {}).values())
    return r


@router.get("/activo/no-planificadas")
def no_planificadas(s: Session = Depends(get_sesion), _: UsuarioActual = Depends(requiere("ver"))) -> list[dict]:
    plan = sv.plan_activo(s)
    return plan.no_planificadas or [] if plan else []


def _asig_json(a: AsignacionPlan, of: OrdenFabricacion, op: Operacion, rec: Recurso | None, opr: Operario | None, ap: Aparato | None, tanda: Tanda | None) -> dict:
    return {
        "operacion_id": a.operacion_id, "of_id": a.of_id, "of": of.numero, "tipo": op.tipo, "seccion": op.seccion_codigo, "grupo_hf": of.grupo_hf,
        "recurso_id": a.recurso_id, "recurso": rec.codigo if rec else None, "unidad": a.unidad, "operario_id": a.operario_id,
        "operario": opr.nombre if opr else None, "operario_codigo": opr.codigo_empleado if opr else None, "inicio": a.inicio.isoformat(),
        "fin": a.fin.isoformat(), "tramos": a.segmentos, "minutos": a.minutos, "prioridad": a.prioridad, "bloqueada": a.bloqueada,
        "provisional": a.provisional, "riesgo": of.riesgo_nivel, "aparato": ap.referencia if ap else ("varios" if of.aparato_id is None else None),
        "aparato_id": of.aparato_id, "tanda": tanda.numero if tanda else None, "tanda_id": of.tanda_id, "estado_op": op.estado, "urgente": of.urgente,
        "familia": op.familia_setup,
    }


def _cargar_asignaciones(s: Session, plan: Plan, desde: datetime | None, hasta: datetime | None) -> list[dict]:
    q = select(AsignacionPlan).where(AsignacionPlan.plan_id == plan.id)
    if desde:
        q = q.where(AsignacionPlan.fin >= desde)
    if hasta:
        q = q.where(AsignacionPlan.inicio <= hasta)
    filas = list(s.scalars(q.order_by(AsignacionPlan.inicio)))
    ofs = {o.id: o for o in s.scalars(select(OrdenFabricacion).where(OrdenFabricacion.id.in_({a.of_id for a in filas})))}
    ops = {o.id: o for o in s.scalars(select(Operacion).where(Operacion.id.in_({a.operacion_id for a in filas})))}
    recs = {r.id: r for r in s.scalars(select(Recurso))}
    oprs = {o.id: o for o in s.scalars(select(Operario))}
    aps = {a.id: a for a in s.scalars(select(Aparato))}
    tandas = {t.id: t for t in s.scalars(select(Tanda))}
    return [_asig_json(a, ofs[a.of_id], ops[a.operacion_id], recs.get(a.recurso_id), oprs.get(a.operario_id), aps.get(ofs[a.of_id].aparato_id), tandas.get(ofs[a.of_id].tanda_id)) for a in filas]


def _calendario(s: Session) -> tuple[set[date], dict[str, set[date]]]:
    """Festivos y días de jornada extra por turno (para dibujar los turnos reales)."""
    festivos = {f.fecha for f in s.scalars(select(Festivo))}
    extras: dict[str, set[date]] = defaultdict(set)
    for j in s.scalars(select(JornadaExtra)):
        extras[j.turno_codigo].add(j.fecha)
    return festivos, extras


@router.get("/activo/gantt")
def gantt(
    desde: datetime | None = None, hasta: datetime | None = None, seccion: str | None = None, tanda_id: int | None = None, recurso_id: int | None = None,
    s: Session = Depends(get_sesion), _: UsuarioActual = Depends(requiere("ver")),
) -> dict:
    plan = sv.plan_activo(s)
    if plan is None:
        return {"plan_id": None, "asignaciones": [], "recursos": [], "turnos": []}
    items = _cargar_asignaciones(s, plan, desde, hasta)
    if seccion:
        items = [i for i in items if i["seccion"] == seccion]
    if tanda_id:
        items = [i for i in items if i["tanda_id"] == tanda_id]
    if recurso_id:
        items = [i for i in items if i["recurso_id"] == recurso_id]
    recursos = [
        {"id": r.id, "codigo": r.codigo, "nombre": r.nombre, "seccion": r.seccion_codigo, "tipo": r.tipo, "estado": r.estado, "capacidad": r.capacidad}
        for r in s.scalars(select(Recurso).where(Recurso.activo.is_(True)).order_by(Recurso.seccion_codigo, Recurso.codigo))
    ]
    ini = desde or (min((datetime.fromisoformat(i["inicio"]) for i in items), default=plan.ahora_referencia))
    fin = hasta or (max((datetime.fromisoformat(i["fin"]) for i in items), default=ini + timedelta(days=7)))
    festivos, extras = _calendario(s)
    turnos = []
    for t in s.scalars(select(Turno).where(Turno.activo.is_(True))):
        for a, b in ventanas_turno(turno_desde_modelo(t), ini - timedelta(days=1), fin + timedelta(days=1), festivos, extras[t.codigo]):
            turnos.append({"turno": t.codigo, "inicio": a.isoformat(), "fin": b.isoformat(), "extra": a.date() in extras[t.codigo]})
    of_ids = {i["of_id"] for i in items}
    dependencias = [
        [d.of_origen_id, d.of_destino_id]
        for d in s.scalars(select(DependenciaOF).where(DependenciaOF.activa.is_(True), DependenciaOF.of_origen_id.in_(of_ids), DependenciaOF.of_destino_id.in_(of_ids)))
    ]
    cfg_semana = configuracion.obtener(s, "semana_fabricacion")
    semanas = sorted({a.semana_codigo for a in s.scalars(select(Aparato).where(Aparato.id.in_({i["aparato_id"] for i in items if i["aparato_id"]}))) if a.semana_codigo})
    limites = [{"semana": w, "fecha": lim.isoformat()} for w in semanas if (lim := limite_semana(w, cfg_semana))]
    operarios = [{"id": o.id, "codigo": o.codigo_empleado, "nombre": o.nombre, "turno": o.turno_codigo} for o in s.scalars(select(Operario).where(Operario.activo.is_(True)).order_by(Operario.codigo_empleado))]
    return {
        "plan_id": plan.id, "ahora": ahora().isoformat(), "asignaciones": items, "recursos": recursos, "turnos": turnos, "no_planificadas": len(plan.no_planificadas or []),
        "dependencias": dependencias, "limites": limites, "operarios": operarios,
    }


@router.get("/activo/capacidad")
def capacidad(dias: int = 14, s: Session = Depends(get_sesion), _: UsuarioActual = Depends(requiere("ver"))) -> dict:
    """Ocupación planificada frente a capacidad real (turnos, jornadas extra, festivos, paradas),
    por recurso y día, y agregada por sección."""
    plan = sv.plan_activo(s)
    momento = ahora()
    inst = cargar_instantanea(s, momento)
    dia0 = momento.date()
    fechas = [dia0 + timedelta(days=i) for i in range(max(1, min(dias, 42)))]
    limites = [(datetime.combine(d, datetime.min.time()), datetime.combine(d + timedelta(days=1), datetime.min.time())) for d in fechas]
    ocupado: dict[int, list[float]] = defaultdict(lambda: [0.0] * len(fechas))
    if plan is not None:
        for a in s.scalars(select(AsignacionPlan).where(AsignacionPlan.plan_id == plan.id, AsignacionPlan.fin >= limites[0][0], AsignacionPlan.inicio <= limites[-1][1])):
            tramos = [(datetime.fromisoformat(x), datetime.fromisoformat(y)) for x, y in (a.segmentos or [[a.inicio.isoformat(), a.fin.isoformat()]])]
            for i, (d0, d1) in enumerate(limites):
                ocupado[a.recurso_id][i] += sum(max(0.0, (min(b, d1) - max(x, d0)).total_seconds() / 60) for x, b in tramos)
    recursos = []
    por_seccion: dict[str, list[list[float]]] = {}
    for r in sorted(inst.recursos.values(), key=lambda r: (r.seccion or "", r.codigo)):
        v = inst.ventanas_recurso(r)
        celdas = []
        for i, (d0, d1) in enumerate(limites):
            disp = v.minutos(max(d0, momento), d1) * max(1, r.capacidad)
            celdas.append({"disponible": round(disp), "ocupado": round(min(ocupado[r.id][i], disp) if disp else ocupado[r.id][i])})
        recursos.append({"id": r.id, "codigo": r.codigo, "nombre": r.nombre, "seccion": r.seccion, "estado": r.estado, "celdas": celdas})
        acc = por_seccion.setdefault(r.seccion or "—", [[0.0, 0.0] for _ in fechas])
        for i, c in enumerate(celdas):
            acc[i][0] += c["disponible"]
            acc[i][1] += c["ocupado"]
    secciones = [{"seccion": k, "celdas": [{"disponible": round(a), "ocupado": round(b)} for a, b in v]} for k, v in sorted(por_seccion.items())]
    return {"plan_id": plan.id if plan else None, "ahora": momento.isoformat(), "dias": [d.isoformat() for d in fechas], "recursos": recursos, "secciones": secciones}


@router.get("/activo/turnos")
def plan_por_turno(dia: date | None = None, s: Session = Depends(get_sesion), _: UsuarioActual = Depends(requiere("ver"))) -> dict:
    """Plan diario por turno: TURNO → operario → máquina → OF (punto 17-18)."""
    plan = sv.plan_activo(s)
    dia = dia or ahora().date()
    if plan is None:
        return {"dia": dia.isoformat(), "turnos": []}
    ini = datetime.combine(dia, datetime.min.time())
    items = _cargar_asignaciones(s, plan, ini, ini + timedelta(days=1, hours=8))
    salida = []
    festivos, extras = _calendario(s)
    for t in s.scalars(select(Turno).where(Turno.activo.is_(True)).order_by(Turno.hora_inicio)):
        ventanas = ventanas_turno(turno_desde_modelo(t), ini, ini + timedelta(days=1, hours=8), festivos, extras[t.codigo])
        ventanas = [v for v in ventanas if v[0].date() == dia or (v[0].date() == dia + timedelta(days=1) and v[0].hour < 6 and t.hora_fin < t.hora_inicio)]
        if not ventanas:
            continue
        t0, t1 = ventanas[0][0], ventanas[-1][1]
        por_operario: dict[str, list[dict]] = defaultdict(list)
        sin_operario: list[dict] = []
        for i in items:
            a, b = datetime.fromisoformat(i["inicio"]), datetime.fromisoformat(i["fin"])
            if b <= t0 or a >= t1:
                continue
            (por_operario[i["operario"]] if i["operario"] else sin_operario).append(i)
        salida.append(
            {
                "turno": t.codigo, "nombre": t.nombre, "inicio": t0.isoformat(), "fin": t1.isoformat(),
                "operarios": [{"operario": k, "trabajos": sorted(v, key=lambda x: x["inicio"])} for k, v in sorted(por_operario.items())],
                "sin_operario": sin_operario,
            }
        )
    return {"dia": dia.isoformat(), "turnos": salida}


@router.get("/activo/cambios")
def cambios(limite: int = 200, s: Session = Depends(get_sesion), _: UsuarioActual = Depends(requiere("ver"))) -> list[dict]:
    """Registro de cambios (ANTES / DESPUÉS / MOTIVO / IMPACTO) de los planes oficiales."""
    planes = [p.id for p in s.scalars(select(Plan).where(Plan.tipo == TipoPlan.OFICIAL))]
    return [
        {
            "id": c.id, "plan_id": c.plan_id, "lote": c.lote, "fecha": c.fecha.isoformat(), "usuario": c.usuario, "tipo": c.tipo, "of": c.of_numero,
            "operacion_id": c.operacion_id, "antes": c.antes, "despues": c.despues, "impacto_min": c.impacto_min, "motivo": c.motivo,
            "riesgo_antes": c.riesgo_antes, "riesgo_despues": c.riesgo_despues,
        }
        for c in s.scalars(select(CambioPlan).where(CambioPlan.plan_id.in_(planes)).order_by(CambioPlan.id.desc()).limit(limite))
    ]


@router.get("/asignaciones/{operacion_id}")
def asignacion(operacion_id: int, s: Session = Depends(get_sesion), _: UsuarioActual = Depends(requiere("ver"))) -> dict:
    plan = sv.plan_activo(s)
    a = s.scalar(select(AsignacionPlan).where(AsignacionPlan.plan_id == plan.id, AsignacionPlan.operacion_id == operacion_id)) if plan else None
    if a is None:
        raise HTTPException(404, "Operación no planificada en el plan activo")
    of = s.get(OrdenFabricacion, a.of_id)
    return {**_asig_json(a, of, s.get(Operacion, a.operacion_id), s.get(Recurso, a.recurso_id) if a.recurso_id else None, s.get(Operario, a.operario_id) if a.operario_id else None, s.get(Aparato, of.aparato_id) if of.aparato_id else None, s.get(Tanda, of.tanda_id) if of.tanda_id else None), "explicacion": a.explicacion}


class Mover(BaseModel):
    inicio: datetime | None = None
    recurso_id: int | None = None
    operario_id: int | None = None
    motivo: str
    bloquear: bool | None = None


@router.post("/asignaciones/{operacion_id}/mover")
def mover(operacion_id: int, datos: Mover, s: Session = Depends(get_sesion), u: UsuarioActual = Depends(requiere("modificar_plan"))) -> dict:
    """Arrastre en el Gantt / cambio de recurso u operario. Pasa SIEMPRE por el motor de restricciones."""
    try:
        return sv.mover_asignacion(s, operacion_id, u.usuario, ahora(), datos.inicio, datos.recurso_id, datos.operario_id, datos.motivo, datos.bloquear)
    except sv.CambioRechazado:
        s.commit()  # se conserva la auditoría del intento rechazado
        raise


class Bloquear(BaseModel):
    bloqueada: bool
    motivo: str | None = None


@router.post("/asignaciones/{operacion_id}/bloquear")
def bloquear(operacion_id: int, datos: Bloquear, s: Session = Depends(get_sesion), u: UsuarioActual = Depends(requiere("modificar_plan"))) -> dict:
    sv.bloquear(s, operacion_id, datos.bloqueada, u.usuario, datos.motivo)
    return {"operacion_id": operacion_id, "bloqueada": datos.bloqueada}


# ------------------------------------------------------------------ simulaciones
class Urgente(BaseModel):
    of_id: int
    motivo: str | None = None


@router.post("/simulaciones/of-urgente")
def of_urgente(datos: Urgente, s: Session = Depends(get_sesion), u: UsuarioActual = Depends(requiere("modificar_plan"))) -> dict:
    return sv.simular_of_urgente(s, datos.of_id, u.usuario, ahora(), datos.motivo)


class Decision(BaseModel):
    aceptar: bool
    motivo: str | None = None


@router.post("/simulaciones/{sim_id}/decidir")
def decidir(sim_id: int, datos: Decision, s: Session = Depends(get_sesion), u: UsuarioActual = Depends(requiere("modificar_plan"))) -> dict:
    return sv.decidir_simulacion(s, sim_id, datos.aceptar, u.usuario, datos.motivo)


class Escenario(BaseModel):
    escenario: dict
    guardar: bool = True


@router.post("/simulaciones/escenario")
def escenario(datos: Escenario, s: Session = Depends(get_sesion), u: UsuarioActual = Depends(requiere("simular"))) -> dict:
    return sv.simular_escenario(s, datos.escenario, u.usuario, ahora(), datos.guardar)


class AplicarEscenario(BaseModel):
    escenario: dict
    motivo: str | None = None


@router.post("/simulaciones/escenario/aplicar")
def aplicar_escenario(datos: AplicarEscenario, s: Session = Depends(get_sesion), u: UsuarioActual = Depends(requiere("planificar"))) -> dict:
    """Hace reales las decisiones del escenario (turnos extra, OF adelantadas, pesos) y replanifica."""
    return sv.aplicar_escenario(s, datos.escenario, u.usuario, ahora(), datos.motivo)


@router.get("/simulaciones")
def simulaciones(s: Session = Depends(get_sesion), _: UsuarioActual = Depends(requiere("ver"))) -> list[dict]:
    return [
        {
            "id": p.id, "nombre": p.nombre, "estado": p.estado, "creado": p.creado.isoformat(), "creado_por": p.creado_por, "escenario": p.escenario, "motivo": p.motivo,
            "plan_base_id": p.plan_base_id, "kpis": p.kpis,
        }
        for p in s.scalars(select(Plan).where(Plan.tipo == TipoPlan.SIMULACION).order_by(Plan.id.desc()).limit(50))
    ]


@router.get("/historico")
def historico(s: Session = Depends(get_sesion), _: UsuarioActual = Depends(requiere("ver"))) -> list[dict]:
    return [
        {"id": p.id, "nombre": p.nombre, "estado": p.estado, "creado": p.creado.isoformat(), "creado_por": p.creado_por, "definitivo": p.definitivo, "motivo": p.motivo, "kpis": p.kpis}
        for p in s.scalars(select(Plan).where(Plan.tipo == TipoPlan.OFICIAL).order_by(Plan.id.desc()).limit(50))
    ]
