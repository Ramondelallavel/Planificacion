"""Simulador what-if (puntos 29 y 54): trabaja sobre una COPIA de la instantánea.

Escenario (todos los campos opcionales):
    {
      "modo": "incremental" | "completo",
      "averias":   [{"recurso_id": 3, "inicio": "2026-09-22T08:00", "horas": 4}],
      "ausencias": [{"operario_id": 7, "inicio": "...", "horas": 8}],
      "faltan_operarios": [{"seccion": "LCH", "cantidad": 2}],
      "adelantar_of": [of_id, ...],                  # se marcan urgentes
      "falta_material": [{"of_id": 12, "desde": "..." | null}],
      "retrasos": [{"operacion_id": 99, "minutos": 90}],
      "recursos_extra": [{"clonar_recurso_id": 5, "cantidad": 1}],
      "pesos_prioridad": {"holgura": 0.5, ...}
    }
Nunca escribe en el plan real; el servicio puede guardar el resultado como plan SIMULACION.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from .analisis import analizar_cuellos, calcular_kpis
from .modelo import AsigP, Instantanea, RecursoP
from .programador import ResultadoProgramacion, programar
from .replanificacion import Evento, aplicar_evento
from .riesgo import calcular_riesgos


def _fecha(txt: str | None, defecto: datetime) -> datetime:
    return datetime.fromisoformat(txt) if txt else defecto


def aplicar_escenario(inst: Instantanea, esc: dict) -> list[str]:
    descr: list[str] = []
    for a in esc.get("averias", []):
        ini = _fecha(a.get("inicio"), inst.ahora)
        fin = ini + timedelta(hours=float(a.get("horas", 0))) if a.get("horas") else None
        aplicar_evento(inst, Evento("AVERIA", "", recurso_id=a["recurso_id"], inicio=ini, fin=fin))
        r = inst.recursos.get(a["recurso_id"])
        descr.append(f"Avería de {r.codigo if r else a['recurso_id']} {('durante ' + str(a['horas']) + ' h') if a.get('horas') else 'sin fin conocido'} desde {ini:%d/%m %H:%M}")
    for a in esc.get("ausencias", []):
        ini = _fecha(a.get("inicio"), inst.ahora)
        fin = ini + timedelta(hours=float(a.get("horas", 8)))
        aplicar_evento(inst, Evento("AUSENCIA", "", operario_id=a["operario_id"], inicio=ini, fin=fin))
        o = inst.operarios.get(a["operario_id"])
        descr.append(f"Ausencia de {o.nombre if o else a['operario_id']} {a.get('horas', 8)} h")
    for f in esc.get("faltan_operarios", []):
        candidatos = [o for o in inst.operarios.values() if f.get("seccion") in {inst.recursos[r].seccion for r in inst.recursos if inst.recursos[r].codigo in o.recursos}]
        for o in candidatos[: int(f.get("cantidad", 1))]:
            o.ausencias = sorted(o.ausencias + [(inst.ahora, inst.horizonte + timedelta(days=365))])
            descr.append(f"Sin {o.nombre} ({o.codigo}) en todo el horizonte")
    for of_id in esc.get("adelantar_of", []):
        aplicar_evento(inst, Evento("OF_URGENTE", "", of_id=of_id))
        descr.append(f"OF {inst.of_numeros.get(of_id, of_id)} marcada urgente")
    for m in esc.get("falta_material", []):
        desde = datetime.fromisoformat(m["desde"]) if m.get("desde") else None
        aplicar_evento(inst, Evento("FALTA_MATERIAL", "", of_id=m["of_id"], material_desde=desde))
        descr.append(f"Falta material OF {inst.of_numeros.get(m['of_id'], m['of_id'])}" + (f" hasta {desde:%d/%m %H:%M}" if desde else " sin fecha"))
    for r in esc.get("retrasos", []):
        aplicar_evento(inst, Evento("RETRASO", "", op_id=r["operacion_id"], minutos_extra=float(r["minutos"])))
        descr.append(f"Operación {r['operacion_id']} +{r['minutos']} min")
    nuevo_id = max(inst.recursos, default=0) + 100000
    for extra in esc.get("recursos_extra", []):
        base = inst.recursos.get(extra["clonar_recurso_id"])
        if base is None:
            continue
        for k in range(int(extra.get("cantidad", 1))):
            nuevo_id += 1
            clon = RecursoP(
                nuevo_id,
                f"{base.codigo}-SIM{k + 1}",
                f"{base.nombre} (simulado)",
                base.seccion,
                base.tipo,
                1,
                base.operaciones,
                base.turnos,
                base.requiere_operario,
                "OPERATIVO",
                [],
                base.restricciones,
            )
            inst.recursos[nuevo_id] = clon
            for o in inst.operarios.values():
                if base.codigo in o.recursos:
                    o.recursos.add(clon.codigo)
            descr.append(f"Recurso adicional {clon.codigo}")
    if esc.get("pesos_prioridad"):
        inst.config["pesos_prioridad"] = {**inst.config["pesos_prioridad"], **esc["pesos_prioridad"]}
        descr.append("Pesos de prioridad modificados")
    inst._ventanas_cache.clear()
    return descr


def _resumen(inst: Instantanea, res: ResultadoProgramacion) -> dict:
    riesgos = calcular_riesgos(inst, res)
    cuellos = analizar_cuellos(inst, res)
    return {"kpis": calcular_kpis(inst, res, riesgos, cuellos), "riesgos": riesgos, "cuellos": cuellos[:8]}


def simular(inst_base: Instantanea, plan_base: dict[int, AsigP] | None, esc: dict, no_plan_base: dict | None = None) -> dict:
    base_res = ResultadoProgramacion(dict(plan_base or {}), dict(no_plan_base or {}), {})
    if plan_base is None:
        base_res = programar(inst_base.copia())
    else:
        from .programador import Programador

        base_res.prioridades = Programador(inst_base).prioridades
    base = _resumen(inst_base, base_res)
    inst = inst_base.copia()
    descr = aplicar_escenario(inst, esc)
    if esc.get("modo", "completo") == "incremental" and plan_base is not None:
        # incremental: se congela el plan base y solo se recoloca lo afectado por cada cambio
        plan = dict(plan_base)
        afectadas: set[int] = set()
        for a in plan.values():
            op = inst.ops.get(a.op_id)
            r = inst.recursos.get(a.recurso_id) if a.recurso_id else None
            o = inst.operarios.get(a.operario_id) if a.operario_id else None
            fuera = (r and any(x0 < b and a0 < x1 for x0, x1 in a.tramos for a0, b in r.paradas)) or (o and any(x0 < b and a0 < x1 for x0, x1 in a.tramos for a0, b in o.ausencias))
            if (
                op is None
                or fuera
                or op.urgente
                or op.material_bloqueado
                or (op.liberacion and op.liberacion > a.inicio)
                or (op.duracion and op.duracion - op.minutos_hechos > a.minutos + 0.5)
            ):
                afectadas.add(a.op_id)
        from .programador import Programador

        cambiado = True
        res = None
        while cambiado:
            fijas = [AsigP(**{**a.__dict__, "fija": True}) for i, a in plan.items() if i not in afectadas and i in inst.ops]
            res = Programador(inst).ejecutar(set(afectadas) | (set(inst.ops) - set(plan) - set(no_plan_base or {})), fijas)
            cambiado = False
            for i in list(afectadas):
                fin = res.asignaciones[i].fin if i in res.asignaciones else None
                for s in inst.sucesoras_op(i):
                    if s in plan and s not in afectadas and (fin is None or plan[s].inicio < fin):
                        afectadas.add(s)
                        cambiado = True
        assert res is not None
    else:
        res = programar(inst)
    sim = _resumen(inst, res)
    cambios = []
    plan_b = base_res.asignaciones
    for op_id, d in res.asignaciones.items():
        a = plan_b.get(op_id)
        if a is None or a.fin != d.fin or a.recurso_id != d.recurso_id:
            delta = (d.fin - a.fin).total_seconds() / 60 if a else None
            cambios.append(
                {
                    "of": inst.of_numeros.get(d.of_id),
                    "operacion_id": op_id,
                    "antes_fin": a.fin.isoformat() if a else None,
                    "despues_fin": d.fin.isoformat(),
                    "impacto_min": None if delta is None else round(delta, 1),
                }
            )
    salen = [n.a_dict() for k, n in res.no_planificadas.items() if k in plan_b]
    comp_tandas = []
    for t_id, t in sim["riesgos"]["tandas"].items():
        b = base["riesgos"]["tandas"].get(t_id, {})
        comp_tandas.append(
            {
                "tanda": t["numero"],
                "riesgo_base": b.get("nivel"),
                "riesgo_simulado": t["nivel"],
                "fin_base": b.get("fin_previsto"),
                "fin_simulado": t["fin_previsto"],
                "motivos": t["motivos"][:3],
            }
        )
    comp_aparatos = []
    for ap_id, a in sim["riesgos"]["aparatos"].items():
        b = base["riesgos"]["aparatos"].get(ap_id, {})
        comp_aparatos.append(
            {
                "aparato": a["referencia"],
                "riesgo_base": b.get("nivel"),
                "riesgo_simulado": a["nivel"],
                "fin_base": b.get("fin_previsto"),
                "fin_simulado": a["fin_previsto"],
                "holgura_base_h": b.get("holgura_h"),
                "holgura_simulada_h": a["holgura_h"],
            }
        )
    cambios.sort(key=lambda c: -(c["impacto_min"] or 0))
    return {
        "escenario": descr,
        "kpis_base": base["kpis"],
        "kpis_simulado": sim["kpis"],
        "tandas": comp_tandas,
        "aparatos": comp_aparatos,
        "cuellos_base": base["cuellos"],
        "cuellos_simulado": sim["cuellos"],
        "cambios": cambios[:200],
        "operaciones_que_salen_del_plan": salen,
        "resultado": res,
        "instantanea": inst,
    }
