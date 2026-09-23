"""Replanificación incremental ante incidencias (puntos 19-21).

1. Se aplica el evento sobre la instantánea (avería, ausencia, falta de material, OF urgente,
   retraso...).
2. Se calcula la ZONA AFECTADA: solo las operaciones que el evento invalida.
3. Todo lo demás se congela tal y como estaba; se recolocan las afectadas.
4. Si alguna recolocada termina más tarde y choca con una sucesora congelada, la sucesora
   entra en la zona afectada y se repite (propagación mínima).
5. Se devuelve el ANTES / DESPUÉS / MOTIVO / IMPACTO de cada operación que cambia y el riesgo
   de cada tanda antes y después.

Para una OF urgente se hace inserción con desplazamiento: primero se colocan sus operaciones
respetando solo lo que está en curso o en la ventana congelada, y después se recolocan las
operaciones desplazadas. Nunca se destruye el plan existente.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta

from .modelo import AsigP, Instantanea
from .programador import Programador, ResultadoProgramacion
from .riesgo import calcular_riesgos


@dataclass
class Evento:
    tipo: str  # AVERIA | AUSENCIA | FALTA_MATERIAL | OF_URGENTE | CAMBIO_PRIORIDAD | RETRASO | OPERACION_LENTA
    descripcion: str
    recurso_id: int | None = None
    operario_id: int | None = None
    of_id: int | None = None
    op_id: int | None = None
    inicio: datetime | None = None
    fin: datetime | None = None
    minutos_extra: float | None = None
    material_desde: datetime | None = None
    prioridad: float | None = None


@dataclass
class ResultadoReplan:
    asignaciones: dict[int, AsigP]
    resultado: ResultadoProgramacion
    afectadas: set[int]
    cambios: list[dict]
    riesgos_antes: dict
    riesgos_despues: dict
    resumen: str
    iteraciones: int = 1
    nuevas_no_planificadas: list[dict] = field(default_factory=list)


def aplicar_evento(inst: Instantanea, ev: Evento) -> None:
    lejos = inst.horizonte + timedelta(days=365)
    if ev.tipo == "AVERIA" and ev.recurso_id in inst.recursos:
        r = inst.recursos[ev.recurso_id]
        r.paradas = sorted(r.paradas + [(ev.inicio or inst.ahora, ev.fin or lejos)])
    elif ev.tipo == "AUSENCIA" and ev.operario_id in inst.operarios:
        o = inst.operarios[ev.operario_id]
        o.ausencias = sorted(o.ausencias + [(ev.inicio or inst.ahora, ev.fin or lejos)])
    elif ev.tipo == "FALTA_MATERIAL" and ev.of_id is not None:
        for i in inst.of_ops.get(ev.of_id, []):
            if ev.material_desde:
                inst.ops[i].liberacion = max(filter(None, [inst.ops[i].liberacion, ev.material_desde]))
            else:
                inst.ops[i].material_bloqueado = True
    elif ev.tipo in ("OF_URGENTE", "CAMBIO_PRIORIDAD") and ev.of_id is not None:
        for i in inst.of_ops.get(ev.of_id, []):
            if ev.tipo == "OF_URGENTE":
                inst.ops[i].urgente = True
            if ev.prioridad is not None:
                inst.ops[i].prioridad_ortems = ev.prioridad
    elif ev.tipo in ("RETRASO", "OPERACION_LENTA") and ev.op_id in inst.ops:
        op = inst.ops[ev.op_id]
        op.duracion = (op.duracion or 0) + (ev.minutos_extra or 0)
    inst._ventanas_cache.clear()


def _solapa(tramos: list, ini: datetime, fin: datetime | None) -> bool:
    return any(b > ini and (fin is None or a < fin) for a, b in tramos)


def zona_afectada(inst: Instantanea, plan: dict[int, AsigP], ev: Evento) -> set[int]:
    afectadas: set[int] = set()
    ini = ev.inicio or inst.ahora
    if ev.tipo == "AVERIA":
        for a in plan.values():
            if a.recurso_id == ev.recurso_id and _solapa(a.tramos, ini, ev.fin):
                afectadas.add(a.op_id)
    elif ev.tipo == "AUSENCIA":
        for a in plan.values():
            if a.operario_id == ev.operario_id and _solapa(a.tramos, ini, ev.fin):
                afectadas.add(a.op_id)
    elif ev.tipo in ("FALTA_MATERIAL", "OF_URGENTE", "CAMBIO_PRIORIDAD"):
        afectadas |= {i for i in inst.of_ops.get(ev.of_id or -1, []) if i in inst.ops}
    elif ev.tipo in ("RETRASO", "OPERACION_LENTA") and ev.op_id is not None:
        afectadas.add(ev.op_id)
    # nunca se mueve lo que está en curso salvo que el propio evento lo interrumpa (avería/ausencia)
    en_curso = {f.op_id for f in inst.fijas}
    if ev.tipo not in ("AVERIA", "AUSENCIA", "RETRASO", "OPERACION_LENTA"):
        afectadas -= en_curso
    return {i for i in afectadas if i in inst.ops}


def _diff(inst: Instantanea, antes: dict[int, AsigP], despues: dict[int, AsigP], motivo: str, no_plan: dict) -> list[dict]:
    cambios = []
    for op_id in sorted(set(antes) | set(despues)):
        a, d = antes.get(op_id), despues.get(op_id)
        if a and d and a.inicio == d.inicio and a.fin == d.fin and a.recurso_id == d.recurso_id and a.operario_id == d.operario_id:
            continue
        op = inst.ops.get(op_id)

        def foto(x: AsigP | None) -> dict | None:
            if x is None:
                return None
            return {
                "inicio": x.inicio.isoformat(),
                "fin": x.fin.isoformat(),
                "recurso": inst.recursos[x.recurso_id].codigo if x.recurso_id in inst.recursos else None,
                "operario": inst.operarios[x.operario_id].codigo if x.operario_id in inst.operarios else None,
                "operario_id": x.operario_id,
            }

        impacto = (d.fin - a.fin).total_seconds() / 60 if (a and d) else None
        cambios.append(
            {
                "operacion_id": op_id,
                "of_id": op.of_id if op else None,
                "of": op.of_numero if op else None,
                "tipo": op.tipo if op else None,
                "antes": foto(a),
                "despues": foto(d),
                "impacto_min": None if impacto is None else round(impacto, 1),
                "motivo": motivo if d else f"{motivo} — sale del plan: {no_plan[op_id].detalle if op_id in no_plan else 'no se ha podido recolocar'}",
            }
        )
    return cambios


def replanificar(inst_antes: Instantanea, plan: dict[int, AsigP], ev: Evento, max_iter: int = 10, no_plan_antes: dict | None = None) -> ResultadoReplan:
    base = Programador(inst_antes)
    riesgos_antes = calcular_riesgos(inst_antes, ResultadoProgramacion(plan, dict(no_plan_antes or {}), base.prioridades))
    inst = inst_antes.copia()
    aplicar_evento(inst, ev)
    congelar = timedelta(minutes=int(inst.config["planificacion"].get("congelar_minutos", 60)))
    afectadas = zona_afectada(inst, plan, ev)
    en_curso = {f.op_id: f for f in inst.fijas}
    iteraciones = 0
    res: ResultadoProgramacion | None = None
    while True:
        iteraciones += 1
        prog = Programador(inst)
        fijas = [AsigP(**{**a.__dict__, "fija": True}) for i, a in plan.items() if i not in afectadas and i in inst.ops]
        fijas += [f for i, f in en_curso.items() if i not in afectadas and i not in plan]
        objetivo = set(afectadas)
        if ev.tipo == "OF_URGENTE" and iteraciones == 1:
            # 1) colocar la urgente respetando solo lo congelado; 2) desplazar lo que choque
            limite_congelado = inst.ahora + congelar
            duras = [a for a in fijas if a.op_id in en_curso or a.inicio < limite_congelado]
            prog_u = Programador(inst, prog.prioridades)
            res_u = prog_u.ejecutar(objetivo, duras)
            tramos_urg = {i: a for i, a in res_u.asignaciones.items() if i in objetivo}
            desplazadas = set()
            for a in fijas:
                if a.op_id in en_curso or a.inicio < limite_congelado:
                    continue
                for u in tramos_urg.values():
                    mismo_rec = a.recurso_id == u.recurso_id and a.unidad == u.unidad
                    mismo_op = a.operario_id is not None and a.operario_id == u.operario_id
                    if (mismo_rec or mismo_op) and any(x0 < y1 and y0 < x1 for x0, x1 in a.tramos for y0, y1 in u.tramos):
                        desplazadas.add(a.op_id)
            fijas_d = [a for a in fijas if a.op_id not in desplazadas] + [AsigP(**{**u.__dict__, "fija": True}) for u in tramos_urg.values()]
            res = Programador(inst, prog.prioridades).ejecutar(desplazadas, fijas_d)
            res.no_planificadas.update({k: v for k, v in res_u.no_planificadas.items() if k in objetivo})
            afectadas |= desplazadas
        else:
            res = prog.ejecutar(objetivo, fijas)
        nuevo = dict(res.asignaciones)
        # propagación: sucesoras congeladas que ahora empezarían antes de que termine su predecesora
        extra: set[int] = set()
        for i in afectadas:
            fin_nuevo = nuevo[i].fin if i in nuevo else None
            for s in inst.sucesoras_op(i):
                if s in afectadas or s not in plan:
                    continue
                if fin_nuevo is None or plan[s].inicio < fin_nuevo:
                    extra.add(s)
        if not extra or iteraciones >= max_iter:
            break
        afectadas |= extra
    assert res is not None
    # lo congelado se devuelve tal cual estaba (con su marca original de bloqueo), lo recolocado es nuevo
    nuevo = {}
    for i, a in res.asignaciones.items():
        if i in plan and i not in afectadas:
            nuevo[i] = plan[i]
        else:
            nuevo[i] = AsigP(**{**a.__dict__, "fija": i in en_curso and i not in afectadas})
    res.asignaciones = nuevo
    if no_plan_antes:
        for k, v in no_plan_antes.items():
            if k in inst.ops and k not in nuevo and k not in res.no_planificadas and k not in afectadas:
                res.no_planificadas[k] = v
    riesgos_despues = calcular_riesgos(inst, res)
    cambios = _diff(inst, {k: v for k, v in plan.items() if k in inst.ops}, nuevo, ev.descripcion, res.no_planificadas)
    retrasos = [c["impacto_min"] for c in cambios if c["impacto_min"]]
    resumen = (
        f"{ev.descripcion}: {len(afectadas)} operaciones en la zona afectada, {len(cambios)} cambian"
        + (f"; retraso máximo {max(retrasos):.0f} min" if retrasos else "")
        + (f"; {sum(1 for c in cambios if c['despues'] is None)} salen del plan" if any(c["despues"] is None for c in cambios) else "")
    )
    nuevas_np = [n.a_dict() for k, n in res.no_planificadas.items() if k in plan]
    return ResultadoReplan(nuevo, res, afectadas, cambios, riesgos_antes, riesgos_despues, resumen, iteraciones, nuevas_np)
