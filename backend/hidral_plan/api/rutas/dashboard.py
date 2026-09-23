"""Control Tower del jefe de equipo y cuadro de mando global (puntos 24, 42, 51-52).

La pantalla principal responde: ¿qué tengo que hacer ahora? ¿qué está en riesgo? ¿por qué?
¿qué pasa si no actúo? ¿qué ha cambiado? Las alertas se agrupan por tanda para no generar
cientos de avisos sueltos.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ...modelos import (
    Aparato,
    AsignacionPlan,
    Ausencia,
    CambioPlan,
    Fichaje,
    IncidenciaProduccion,
    OFAparato,
    Operacion,
    Operario,
    OrdenFabricacion,
    Recurso,
    Tanda,
    Turno,
)
from ...modelos.enums import ORDEN_RIESGO, EstadoOF, EstadoRecurso, NivelRiesgo
from ...planificacion import servicio as sv
from ...planificacion.calendario import turno_desde_modelo, ventanas_turno
from ..deps import UsuarioActual, ahora, get_sesion, requiere

router = APIRouter(prefix="/dashboard", tags=["control"])

ACCION_POR_MOTIVO = {
    "SIN_DURACION": "Configurar el tiempo estándar (o importar la ruta de MRP) de {n} operaciones",
    "SIN_RECURSO": "Asignar recurso capaz (o informar fecha prevista si son OF externas) a {n} operaciones",
    "SIN_OPERARIO": "Cualificar operarios para {n} operaciones sin personal",
    "PREDECESORA_NO_PLANIFICABLE": "{n} operaciones esperan a predecesoras bloqueadas",
    "PREDECESORA_EXTERNA": "Informar la disponibilidad de OF externas de las que dependen {n} operaciones",
    "ESPERANDO_MATERIAL": "Confirmar fecha de material de {n} operaciones",
    "BLOQUEADA": "{n} operaciones de OF bloqueadas manualmente",
    "SIN_HUECO": "Añadir capacidad: {n} operaciones no caben en el horizonte",
    "PENDIENTE_PROGRAMACION": "Registrar programas de máquina de {n} operaciones",
}


def _peor(niveles) -> str:
    return max(niveles, key=lambda n: ORDEN_RIESGO[NivelRiesgo(n)], default=NivelRiesgo.VERDE)


def _personal(s: Session, momento: datetime) -> dict:
    turnos_ahora = set()
    for t in s.scalars(select(Turno).where(Turno.activo.is_(True))):
        for a, b in ventanas_turno(turno_desde_modelo(t), momento - timedelta(hours=12), momento + timedelta(hours=1)):
            if a <= momento < b:
                turnos_ahora.add(t.codigo)
    # la pausa del turno no convierte a la plantilla en "fuera de turno"
    for t in s.scalars(select(Turno).where(Turno.activo.is_(True))):
        ini = datetime.combine(momento.date(), datetime.strptime(t.hora_inicio, "%H:%M").time())
        fin = datetime.combine(momento.date(), datetime.strptime(t.hora_fin, "%H:%M").time())
        if fin <= ini:
            fin += timedelta(days=1)
        if ini <= momento < fin and momento.weekday() in (t.dias_semana or []):
            turnos_ahora.add(t.codigo)
    ausentes = {a.operario_id for a in s.scalars(select(Ausencia).where(Ausencia.inicio <= momento, (Ausencia.fin.is_(None)) | (Ausencia.fin > momento)))}
    ocupados = {f.operario_id for f in s.scalars(select(Fichaje).where(Fichaje.estado.in_(["ABIERTO", "PAUSADO"])))}
    ops = list(s.scalars(select(Operario).where(Operario.activo.is_(True))))
    en_turno = [o for o in ops if o.turno_codigo in turnos_ahora]
    return {
        "en_turno": len(en_turno),
        "ausentes": len([o for o in ops if o.id in ausentes]),
        "ocupados": len([o for o in en_turno if o.id in ocupados and o.id not in ausentes]),
        "disponibles": len([o for o in en_turno if o.id not in ausentes and o.id not in ocupados]),
        "total": len(ops),
        "turnos_activos": sorted(turnos_ahora),
    }


@router.get("/control-tower")
def control_tower(s: Session = Depends(get_sesion), _: UsuarioActual = Depends(requiere("ver"))) -> dict:
    momento = ahora()
    plan = sv.plan_activo(s)
    riesgos = (plan.riesgos or {}) if plan else {}
    tandas_r = riesgos.get("tandas", {})
    aparatos_r = riesgos.get("aparatos", {})
    cuellos = [c for c in riesgos.get("cuellos", []) if c.get("nivel") in (NivelRiesgo.ROJO, NivelRiesgo.NARANJA, NivelRiesgo.AMARILLO)]
    no_plan = plan.no_planificadas or [] if plan else []
    tandas = {t.id: t for t in s.scalars(select(Tanda).where(Tanda.estado == "ACTIVA"))}

    paradas = [r for r in s.scalars(select(Recurso).where(Recurso.activo.is_(True), Recurso.estado != EstadoRecurso.OPERATIVO))]
    incidencias = list(s.scalars(select(IncidenciaProduccion).where(IncidenciaProduccion.estado == "ABIERTA")))
    of_tanda = dict(s.execute(select(OrdenFabricacion.id, OrdenFabricacion.tanda_id)).all())
    of_num = dict(s.execute(select(OrdenFabricacion.id, OrdenFabricacion.numero)).all())

    # OF retrasadas: debían haber empezado según el plan y no han empezado; o terminan fuera de semana
    retrasadas = []
    if plan:
        tolerancia = momento - timedelta(minutes=30)
        for a, op, of in s.execute(
            select(AsignacionPlan, Operacion, OrdenFabricacion)
            .join(Operacion, Operacion.id == AsignacionPlan.operacion_id)
            .join(OrdenFabricacion, OrdenFabricacion.id == AsignacionPlan.of_id)
            .where(AsignacionPlan.plan_id == plan.id, AsignacionPlan.inicio < tolerancia, Operacion.estado.in_(["PENDIENTE", "PLANIFICADA", "LISTA", "PENDIENTE_PROGRAMACION"]))
        ):
            retrasadas.append({"of": of.numero, "of_id": of.id, "tipo": op.tipo, "inicio_previsto": a.inicio.isoformat(), "motivo": "debía haber empezado según el plan", "tanda_id": of.tanda_id})
        for k, r in riesgos.get("ofs", {}).items():
            if r.get("nivel") == NivelRiesgo.ROJO and r.get("fin_previsto") and r.get("holgura_h") is not None and r["holgura_h"] < 0:
                retrasadas.append({"of": r["of"], "of_id": int(k), "tipo": None, "inicio_previsto": None, "motivo": r["motivos"][0] if r["motivos"] else "fuera de semana", "tanda_id": of_tanda.get(int(k))})

    # ---- alertas agrupadas por tanda
    alertas = []
    por_tanda_np: dict[int | None, list[dict]] = defaultdict(list)
    for n in no_plan:
        por_tanda_np[of_tanda.get(n["of_id"])].append(n)
    for t_id, t in tandas.items():
        detalles: list[dict] = []
        niveles: list[str] = []
        tr = tandas_r.get(str(t_id))
        for ap in (a for a in aparatos_r.values() if a.get("tanda_id") == t_id):
            if ap["nivel"] != NivelRiesgo.VERDE:
                niveles.append(ap["nivel"])
                detalles.append({"nivel": ap["nivel"], "texto": f"Aparato {ap['referencia']}: {ap['motivos'][0] if ap['motivos'] else ''}", "acciones": ap.get("acciones", [])})
        np_t = por_tanda_np.get(t_id, [])
        if np_t:
            motivos = Counter(n["motivo"] for n in np_t)
            for motivo, cnt in motivos.most_common():
                ejemplo = next(n for n in np_t if n["motivo"] == motivo)
                detalles.append({"nivel": NivelRiesgo.ROJO if motivo != "PREDECESORA_NO_PLANIFICABLE" else NivelRiesgo.NARANJA, "texto": f"{cnt} operaciones no planificables ({motivo}): p.ej. OF {ejemplo['of']} — {ejemplo['detalle']}", "acciones": [ACCION_POR_MOTIVO.get(motivo, "Revisar").format(n=cnt)]})
                niveles.append(NivelRiesgo.ROJO if motivo != "PREDECESORA_NO_PLANIFICABLE" else NivelRiesgo.NARANJA)
        for inc in incidencias:
            if inc.of_id and of_tanda.get(inc.of_id) == t_id:
                detalles.append({"nivel": NivelRiesgo.NARANJA, "texto": f"Incidencia {inc.tipo} en OF {of_num.get(inc.of_id)}: {inc.descripcion}", "acciones": []})
                niveles.append(NivelRiesgo.NARANJA)
        for r in paradas:
            afectadas = s.scalar(
                select(func.count(AsignacionPlan.id)).where(AsignacionPlan.plan_id == plan.id, AsignacionPlan.recurso_id == r.id, AsignacionPlan.of_id.in_([k for k, v in of_tanda.items() if v == t_id]))
            ) if plan else 0
            if afectadas:
                detalles.append({"nivel": NivelRiesgo.ROJO, "texto": f"Máquina {r.codigo} {r.estado}: {afectadas} operaciones de la tanda la usan", "acciones": ["Registrar la avería como incidencia para replanificar la zona afectada"]})
                niveles.append(NivelRiesgo.ROJO)
        ret = [x for x in retrasadas if x["tanda_id"] == t_id]
        if ret:
            detalles.append({"nivel": NivelRiesgo.NARANJA, "texto": f"{len(ret)} OF retrasadas (p.ej. {ret[0]['of']}: {ret[0]['motivo']})", "acciones": ["Revisar causa y fichajes; replanificar si procede"]})
            niveles.append(NivelRiesgo.NARANJA)
        pend = s.scalar(select(func.count(OrdenFabricacion.id)).where(OrdenFabricacion.tanda_id == t_id, OrdenFabricacion.estado_programacion == "PENDIENTE_PROGRAMACION"))
        if pend:
            detalles.append({"nivel": NivelRiesgo.AMARILLO, "texto": f"{pend} OF pendientes de programación (LCH/LaserTub): plan provisional", "acciones": ["Registrar los programas en cuanto estén hechos"]})
            niveles.append(NivelRiesgo.AMARILLO)
        nivel = _peor(niveles) if niveles else (tr["nivel"] if tr else NivelRiesgo.VERDE)
        alertas.append(
            {
                "tanda_id": t_id, "tanda": t.numero, "semana": t.semana_codigo, "nivel": nivel,
                "titulo": f"{len(detalles)} {'incidencias afectan' if len(detalles) != 1 else 'incidencia afecta'} a TANDA {t.numero}" if detalles else f"TANDA {t.numero} sin incidencias",
                "detalles": sorted(detalles, key=lambda d: -ORDEN_RIESGO[NivelRiesgo(d["nivel"])]),
                "impacto": (tr or {}).get("motivos", [])[:3],
                "fin_previsto": (tr or {}).get("fin_previsto"),
            }
        )
    alertas.sort(key=lambda a: -ORDEN_RIESGO[NivelRiesgo(a["nivel"])])

    # ---- qué hacer ahora: trabajos en curso o que empiezan en las próximas 2 h
    ahora_hacer = []
    if plan:
        for a, op, of, rec, opr in s.execute(
            select(AsignacionPlan, Operacion, OrdenFabricacion, Recurso, Operario)
            .join(Operacion, Operacion.id == AsignacionPlan.operacion_id)
            .join(OrdenFabricacion, OrdenFabricacion.id == AsignacionPlan.of_id)
            .outerjoin(Recurso, Recurso.id == AsignacionPlan.recurso_id)
            .outerjoin(Operario, Operario.id == AsignacionPlan.operario_id)
            .where(AsignacionPlan.plan_id == plan.id, AsignacionPlan.inicio <= momento + timedelta(hours=2), AsignacionPlan.fin >= momento)
            .order_by(AsignacionPlan.inicio)
            .limit(40)
        ):
            ahora_hacer.append(
                {
                    "operacion_id": op.id, "of": of.numero, "of_id": of.id, "tipo": op.tipo, "recurso": rec.codigo if rec else None, "operario": opr.nombre if opr else None,
                    "inicio": a.inicio.isoformat(), "fin": a.fin.isoformat(), "estado": op.estado, "provisional": a.provisional, "riesgo": of.riesgo_nivel,
                    "prioridad": a.prioridad, "motivo": ((a.explicacion or {}).get("prioridad") or {}).get("motivos", [])[:2],
                }
            )

    acciones = []
    for ap in sorted(aparatos_r.values(), key=lambda a: -ORDEN_RIESGO[NivelRiesgo(a["nivel"])]):
        for acc in ap.get("acciones", []):
            acciones.append({"nivel": ap["nivel"], "texto": f"{ap['referencia']}: {acc}"})
    for motivo, cnt in Counter(n["motivo"] for n in no_plan).most_common():
        acciones.append({"nivel": NivelRiesgo.ROJO if motivo not in ("PREDECESORA_NO_PLANIFICABLE",) else NivelRiesgo.NARANJA, "texto": ACCION_POR_MOTIVO.get(motivo, motivo).format(n=cnt)})

    cambios = [
        {"fecha": c.fecha.isoformat(), "tipo": c.tipo, "of": c.of_numero, "antes": c.antes, "despues": c.despues, "impacto_min": c.impacto_min, "motivo": c.motivo, "usuario": c.usuario}
        for c in s.scalars(select(CambioPlan).where(CambioPlan.plan_id == (plan.id if plan else -1), CambioPlan.tipo != "GENERACION").order_by(CambioPlan.id.desc()).limit(15))
    ]
    personal = _personal(s, momento)
    aparatos_en_riesgo = [a for a in aparatos_r.values() if a["nivel"] != NivelRiesgo.VERDE]
    return {
        "ahora": momento.isoformat(),
        "plan": {"id": plan.id, "nombre": plan.nombre, "creado": plan.creado.isoformat(), "kpis": plan.kpis, "definitivo": plan.definitivo} if plan else None,
        "resumen": {
            "tandas_en_curso": len(tandas),
            "tandas_en_riesgo": sum(1 for a in alertas if a["nivel"] != NivelRiesgo.VERDE),
            "aparatos_en_riesgo": len(aparatos_en_riesgo),
            "ofs_retrasadas": len({x["of"] for x in retrasadas}),
            "maquinas_paradas": len(paradas),
            "incidencias_abiertas": len(incidencias),
            "trabajadores_disponibles": personal["disponibles"],
            "trabajadores_ausentes": personal["ausentes"],
            "cuellos_botella": len([c for c in cuellos if c["nivel"] in (NivelRiesgo.ROJO, NivelRiesgo.NARANJA)]),
            "no_planificadas": len(no_plan),
        },
        "personal": personal,
        "alertas": alertas,
        "tandas": sorted(tandas_r.values(), key=lambda t: -ORDEN_RIESGO[NivelRiesgo(t["nivel"])]),
        "aparatos": sorted(aparatos_r.values(), key=lambda a: -ORDEN_RIESGO[NivelRiesgo(a["nivel"])]),
        "cuellos": cuellos[:6],
        "maquinas_paradas": [{"codigo": r.codigo, "nombre": r.nombre, "estado": r.estado} for r in paradas],
        "ahora_hacer": ahora_hacer,
        "acciones_recomendadas": acciones[:12],
        "cambios_recientes": cambios,
        "retrasadas": retrasadas[:30],
    }


@router.get("/global")
def global_(s: Session = Depends(get_sesion), _: UsuarioActual = Depends(requiere("ver"))) -> dict:
    momento = ahora()
    hoy = datetime.combine(momento.date(), datetime.min.time())
    plan = sv.plan_activo(s)
    kpis = (plan.kpis or {}) if plan else {}
    riesgos = (plan.riesgos or {}) if plan else {}
    terminadas_hoy = s.scalar(select(func.count(OrdenFabricacion.id)).where(OrdenFabricacion.fecha_real_fin >= hoy))
    pendientes = s.scalar(select(func.count(OrdenFabricacion.id)).where(OrdenFabricacion.estado.not_in([EstadoOF.TERMINADA, EstadoOF.VALIDADA]), OrdenFabricacion.tiene_hoja.is_(True)))
    horas_prev = s.scalar(select(func.sum(Operacion.duracion_estimada_min)).where(Operacion.estado != "TERMINADA")) or 0
    fich_hoy = list(s.scalars(select(Fichaje).where(Fichaje.estado == "CERRADO", Fichaje.fin >= hoy)))
    horas_reales_hoy = sum(f.duracion_real_min or 0 for f in fich_hoy) / 60
    horas_plan_hoy = sum(f.duracion_planificada_min or 0 for f in fich_hoy) / 60
    tandas_r = list(riesgos.get("tandas", {}).values())
    aparatos_r = list(riesgos.get("aparatos", {}).values())
    completos = 0
    for ap in s.scalars(select(Aparato)):
        ofs = [o for (o,) in s.execute(select(OrdenFabricacion.estado).join(OFAparato, OFAparato.of_id == OrdenFabricacion.id).where(OFAparato.aparato_id == ap.id))]
        if ofs and all(o in (EstadoOF.TERMINADA, EstadoOF.VALIDADA) for o in ofs):
            completos += 1
    cuellos = riesgos.get("cuellos", [])
    incid = Counter(i.tipo for i in s.scalars(select(IncidenciaProduccion).where(IncidenciaProduccion.estado == "ABIERTA")))
    return {
        "produccion": {
            "of_terminadas_hoy": terminadas_hoy, "of_pendientes": pendientes, "horas_previstas_pendientes": round(horas_prev / 60, 1),
            "horas_reales_hoy": round(horas_reales_hoy, 1), "horas_planificadas_de_lo_fichado_hoy": round(horas_plan_hoy, 1),
            "desviacion_hoy_pct": round(100 * (horas_reales_hoy - horas_plan_hoy) / horas_plan_hoy, 1) if horas_plan_hoy else None,
            "cumplimiento_semana": kpis.get("cumplimiento_semana"),
        },
        "tandas": {
            "en_plazo": sum(1 for t in tandas_r if t["nivel"] == NivelRiesgo.VERDE), "riesgo": sum(1 for t in tandas_r if t["nivel"] in (NivelRiesgo.AMARILLO, NivelRiesgo.NARANJA)),
            "retrasadas": sum(1 for t in tandas_r if t["nivel"] == NivelRiesgo.ROJO),
        },
        "aparatos": {"completos": completos, "en_proceso": sum(1 for a in aparatos_r if a["ofs_pendientes"]), "bloqueados": sum(1 for a in aparatos_r if a.get("ofs_no_planificables"))},
        "recursos": {
            "ocupacion": [{"codigo": c["codigo"], "utilizacion": c["utilizacion"], "nivel": c["nivel"]} for c in cuellos[:12]],
            "paradas": s.scalar(select(func.count(Recurso.id)).where(Recurso.estado != EstadoRecurso.OPERATIVO)),
            "utilizacion_media": kpis.get("utilizacion_media"),
        },
        "personal": _personal(s, momento),
        "calidad": {"incidencias_abiertas": sum(incid.values()), "por_tipo": dict(incid), "retrabajos": incid.get("CALIDAD", 0)},
        "plan": {k: kpis.get(k) for k in ("planificadas", "no_planificadas", "provisionales", "horas_planificadas", "fin_plan", "cambios_setup", "horas_muertas", "wip_medio_of", "retraso_total_h")},
    }
