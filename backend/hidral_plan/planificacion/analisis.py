"""Cuellos de botella (punto 28) e indicadores de calidad del plan (punto 45)."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta

from ..modelos.enums import ORDEN_RIESGO, NivelRiesgo
from .modelo import AsigP, Instantanea
from .programador import ResultadoProgramacion


def analizar_cuellos(inst: Instantanea, res: ResultadoProgramacion) -> list[dict]:
    umbral = float(inst.config["umbrales_riesgo"].get("utilizacion_cuello_botella", 0.85))
    por_rec: dict[int, list[AsigP]] = defaultdict(list)
    for a in res.asignaciones.values():
        if a.recurso_id is not None:
            por_rec[a.recurso_id].append(a)
    limites = [op.limite for op in inst.ops.values() if op.limite and op.limite > inst.ahora]
    hasta = min(inst.horizonte, max(limites) + timedelta(days=1)) if limites else inst.horizonte
    salida = []
    for r in inst.recursos.values():
        asigs = sorted(por_rec.get(r.id, []), key=lambda a: a.inicio)
        vent = inst.ventanas_recurso(r)
        capacidad = vent.minutos(inst.ahora, hasta) * r.capacidad
        demanda = sum(sum(min(b, hasta).timestamp() - max(a, inst.ahora).timestamp() for a, b in x.tramos if b > inst.ahora and a < hasta) / 60 for x in asigs)
        util = demanda / capacidad if capacidad > 0 else (1.0 if demanda else 0.0)
        # saturación continua desde ahora: tiempo laborable seguido sin huecos > 15 min
        ocupados = sorted(t for x in asigs for t in x.tramos if t[1] > inst.ahora)
        saturado_h = 0.0
        if ocupados and r.capacidad == 1:
            cursor = vent.siguiente_inicio(inst.ahora) or inst.ahora
            for a, b in ocupados:
                if a > cursor:
                    hueco = vent.minutos(cursor, a)
                    if hueco > 15:
                        break
                saturado_h += vent.minutos(max(a, cursor), b) / 60
                cursor = max(cursor, b)
        cola = sum(1 for x in asigs if x.inicio > inst.ahora)
        no_plan = sum(1 for n in res.no_planificadas.values() if inst.ops[n.op_id].seccion == r.seccion and n.motivo in ("SIN_HUECO",))
        if util >= 1.0 or no_plan:
            nivel = NivelRiesgo.ROJO
        elif util >= umbral or r.id in res.cuellos_previstos:
            nivel = NivelRiesgo.NARANJA
        elif util >= 0.7:
            nivel = NivelRiesgo.AMARILLO
        else:
            nivel = NivelRiesgo.VERDE
        mensaje = None
        if nivel in (NivelRiesgo.ROJO, NivelRiesgo.NARANJA) and saturado_h >= 1:
            mensaje = f"{r.codigo} será el cuello de botella estimado durante las próximas {saturado_h:.0f} horas laborables."
        elif nivel in (NivelRiesgo.ROJO, NivelRiesgo.NARANJA):
            mensaje = f"{r.codigo} con utilización prevista del {util * 100:.0f}% hasta el límite de las semanas en curso."
        salida.append(
            {
                "recurso_id": r.id,
                "codigo": r.codigo,
                "nombre": r.nombre,
                "seccion": r.seccion,
                "estado": r.estado,
                "demanda_h": round(demanda / 60, 1),
                "capacidad_h": round(capacidad / 60, 1),
                "utilizacion": round(util, 3),
                "cola": cola,
                "saturado_h": round(saturado_h, 1),
                "nivel": nivel,
                "mensaje": mensaje,
                "impacto": f"{cola} operaciones en cola" if cola else None,
            }
        )
    salida.sort(key=lambda x: (-ORDEN_RIESGO[NivelRiesgo(x["nivel"])], -x["utilizacion"]))
    return salida


def calcular_kpis(inst: Instantanea, res: ResultadoProgramacion, riesgos: dict, cuellos: list[dict]) -> dict:
    asigs = list(res.asignaciones.values())
    por_unidad: dict[tuple, list[AsigP]] = defaultdict(list)
    for a in asigs:
        por_unidad[(a.recurso_id, a.unidad)].append(a)
    setups = 0
    muertas = 0.0
    for (rid, _), lista in por_unidad.items():
        lista.sort(key=lambda a: a.inicio)
        fams = [inst.ops[a.op_id].familia for a in lista if a.op_id in inst.ops]
        setups += sum(1 for x, y in zip(fams, fams[1:], strict=False) if x != y)
        if rid is not None and lista:
            vent = inst.ventanas_recurso(inst.recursos[rid])
            util = vent.minutos(lista[0].inicio, max(a.fin for a in lista))
            muertas += max(0.0, util - sum(a.minutos for a in lista))
    aps = list(riesgos["aparatos"].values())
    evaluables = [a for a in aps if a["ofs_pendientes"]]
    en_plazo = [a for a in evaluables if a["nivel"] in (NivelRiesgo.VERDE, NivelRiesgo.AMARILLO, NivelRiesgo.NARANJA) and a["ofs_no_planificables"] == 0 and a["fin_previsto"]]
    retraso = sum(-a["holgura_h"] for a in evaluables if a["holgura_h"] is not None and a["holgura_h"] < 0)
    # WIP medio: nº de OF abiertas (entre su primera y última operación planificada) a lo largo del plan
    rangos: dict[int, list[datetime]] = {}
    for a in asigs:
        r = rangos.setdefault(a.of_id, [a.inicio, a.fin])
        r[0], r[1] = min(r[0], a.inicio), max(r[1], a.fin)
    wip = 0.0
    if rangos:
        t0 = min(r[0] for r in rangos.values())
        t1 = max(r[1] for r in rangos.values())
        dur = (t1 - t0).total_seconds() or 1
        wip = sum((r[1] - r[0]).total_seconds() for r in rangos.values()) / dur
    horas = sum(a.minutos for a in asigs) / 60
    return {
        "operaciones": len(inst.ops),
        "planificadas": len(asigs),
        "no_planificadas": len(res.no_planificadas),
        "provisionales": sum(1 for a in asigs if a.provisional),
        "horas_planificadas": round(horas, 1),
        "fin_plan": max((a.fin for a in asigs), default=None).isoformat() if asigs else None,
        "cumplimiento_semana": round(len(en_plazo) / len(evaluables), 3) if evaluables else None,
        "aparatos_evaluados": len(evaluables),
        "aparatos_en_plazo": len(en_plazo),
        "retraso_total_h": round(retraso, 1),
        "cambios_setup": setups,
        "horas_muertas": round(muertas / 60, 1),
        "wip_medio_of": round(wip, 1),
        "utilizacion_media": round(sum(c["utilizacion"] for c in cuellos if c["demanda_h"]) / max(1, sum(1 for c in cuellos if c["demanda_h"])), 3),
        "recursos_criticos": [c["codigo"] for c in cuellos if c["nivel"] in (NivelRiesgo.ROJO, NivelRiesgo.NARANJA)],
        "tandas_en_riesgo": sum(1 for t in riesgos["tandas"].values() if t["nivel"] != NivelRiesgo.VERDE),
        "carga_por_recurso": {c["codigo"]: c["demanda_h"] for c in cuellos},
    }
