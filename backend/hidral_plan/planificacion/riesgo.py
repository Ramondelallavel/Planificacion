"""Riesgo de OF, aparato, tanda y recurso (punto 15).

El objetivo no es fabricar muchas piezas sino que ningún aparato/tanda llegue a su semana
de fabricación incompleto. El riesgo se calcula sobre el plan resultante: fin previsto frente
al límite de la semana, holgura en horas laborables, operaciones que no se pueden planificar
(por falta de datos, recursos o predecesoras) y trabajo provisional pendiente de programación.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime

from ..modelos.enums import ORDEN_RIESGO, NivelRiesgo
from .modelo import Instantanea
from .programador import ResultadoProgramacion


def _peor(niveles: list[str]) -> str:
    return max(niveles, key=lambda n: ORDEN_RIESGO[NivelRiesgo(n)], default=NivelRiesgo.VERDE)


def _fmt(d: datetime | None) -> str:
    return d.strftime("%d/%m %H:%M") if d else "—"


def calcular_riesgos(inst: Instantanea, res: ResultadoProgramacion) -> dict:
    umb = inst.config["umbrales_riesgo"]
    naranja_h = float(umb.get("naranja_holgura_h", 8))
    amarillo_h = float(umb.get("amarillo_holgura_h", 24))

    # ---- OF
    fin_of: dict[int, datetime | None] = {}
    no_plan_of: dict[int, list[str]] = defaultdict(list)
    provisional_of: set[int] = set()
    restante_of: dict[int, float] = defaultdict(float)
    for of_id, ops in inst.of_ops.items():
        fines = []
        for i in ops:
            op = inst.ops[i]
            restante_of[of_id] += max(0.0, (op.duracion or 0.0) - op.minutos_hechos)
            if i in res.asignaciones:
                fines.append(res.asignaciones[i].fin)
                if res.asignaciones[i].provisional:
                    provisional_of.add(of_id)
            elif i in res.fin_virtual:
                fines.append(res.fin_virtual[i])
            elif i in res.no_planificadas:
                no_plan_of[of_id].append(res.no_planificadas[i].detalle)
        fin_of[of_id] = None if no_plan_of.get(of_id) else (max(fines) if fines else None)

    ofs_riesgo: dict[int, dict] = {}
    for of_id, ops in inst.of_ops.items():
        op0 = inst.ops[ops[0]]
        motivos: list[str] = []
        limite = op0.limite
        prio = res.prioridades.get(ops[-1])
        cadena_despues = max(0.0, (prio.cadena_h if prio else 0.0) - (inst.ops[ops[-1]].duracion or 0) / 60)
        fin = fin_of.get(of_id)
        holgura = None
        if no_plan_of.get(of_id):
            nivel = NivelRiesgo.ROJO
            motivos.append("No planificable: " + no_plan_of[of_id][0])
        elif limite is None:
            nivel = NivelRiesgo.AMARILLO
            motivos.append("Semana de fabricación DATO NO DISPONIBLE: no se puede evaluar el plazo")
        elif fin is None:
            nivel = NivelRiesgo.AMARILLO
            motivos.append("Sin operaciones planificadas")
        else:
            holgura = inst.horas_laborables(fin, limite) - cadena_despues
            if holgura < 0:
                nivel = NivelRiesgo.ROJO
                motivos.append(f"Termina el {_fmt(fin)} y lo que va detrás necesita {cadena_despues:.1f} h: faltan {-holgura:.1f} h laborables para cumplir la semana {op0.semana}")
            elif holgura < naranja_h:
                nivel = NivelRiesgo.NARANJA
                motivos.append(f"Holgura de solo {holgura:.1f} h laborables respecto a la semana {op0.semana}")
            elif holgura < amarillo_h:
                nivel = NivelRiesgo.AMARILLO
                motivos.append(f"Holgura {holgura:.1f} h laborables")
            else:
                nivel = NivelRiesgo.VERDE
        if of_id in provisional_of:
            motivos.append("Pendiente de programación: el plan es provisional hasta registrar el programa")
            if nivel == NivelRiesgo.VERDE:
                nivel = NivelRiesgo.AMARILLO
        ofs_riesgo[of_id] = {
            "of_id": of_id,
            "of": inst.of_numeros.get(of_id),
            "nivel": nivel,
            "motivos": motivos,
            "fin_previsto": fin.isoformat() if fin else None,
            "holgura_h": None if holgura is None else round(holgura, 1),
            "horas_restantes": round(restante_of[of_id] / 60, 2),
            "limite": limite.isoformat() if limite else None,
        }

    # ---- Aparatos
    ofs_por_aparato: dict[int, set[int]] = defaultdict(set)
    for op in inst.ops.values():
        for ap in op.aparatos:
            ofs_por_aparato[ap].add(op.of_id)
    aparatos: dict[int, dict] = {}
    for ap_id, ap in inst.aparatos.items():
        ofs = ofs_por_aparato.get(ap_id, set())
        motivos: list[str] = []
        acciones: list[str] = []
        if not ofs:
            total = inst.ops_totales_por_aparato.get(ap_id, 0)
            aparatos[ap_id] = {
                "aparato_id": ap_id,
                "referencia": ap.referencia,
                "tanda_id": ap.tanda_id,
                "nivel": NivelRiesgo.VERDE,
                "motivos": ["Sin operaciones pendientes" if total else "Sin operaciones asociadas"],
                "fin_previsto": None,
                "holgura_h": None,
                "horas_restantes": 0.0,
                "semana": ap.semana,
                "limite": ap.limite.isoformat() if ap.limite else None,
                "ofs_pendientes": 0,
                "ofs_no_planificables": 0,
                "acciones": [],
            }
            continue
        bloqueadas = [of for of in ofs if no_plan_of.get(of)]
        fines = [fin_of[of] for of in ofs if fin_of.get(of)]
        fin = max(fines) if fines else None
        horas_rest = sum(restante_of[of] for of in ofs) / 60
        holgura = None
        if bloqueadas:
            nivel = NivelRiesgo.ROJO
            ejemplos = ", ".join(inst.of_numeros[o] for o in sorted(bloqueadas)[:5])
            motivos.append(f"{len(bloqueadas)} OF no se pueden planificar ({ejemplos}{'…' if len(bloqueadas) > 5 else ''}): no se puede garantizar la semana")
            motivos.append(no_plan_of[sorted(bloqueadas)[0]][0])
            acciones.append("Resolver los datos o recursos que faltan (ver 'No planificadas') y regenerar el plan")
        elif ap.limite is None:
            nivel = NivelRiesgo.AMARILLO
            motivos.append("Semana de fabricación DATO NO DISPONIBLE")
        elif fin is None:
            nivel = NivelRiesgo.AMARILLO
            motivos.append("Sin fin previsto")
        else:
            holgura = inst.horas_laborables(fin, ap.limite)
            if fin > ap.limite:
                nivel = NivelRiesgo.ROJO
                motivos.append(f"Con el plan actual termina el {_fmt(fin)}, {-holgura:.1f} h laborables después del límite de la semana {ap.semana}")
                acciones.append("Adelantar sus OF críticas, añadir capacidad (turno/operario) en el recurso que las retrasa o renegociar la semana")
            elif holgura < naranja_h:
                nivel = NivelRiesgo.NARANJA
                motivos.append(f"Termina el {_fmt(fin)} con solo {holgura:.1f} h laborables de margen")
                acciones.append("Vigilar las OF de su camino crítico: cualquier incidencia lo saca de plazo")
            elif holgura < amarillo_h:
                nivel = NivelRiesgo.AMARILLO
                motivos.append(f"Termina el {_fmt(fin)} con {holgura:.1f} h laborables de margen")
            else:
                nivel = NivelRiesgo.VERDE
                motivos.append(f"Termina el {_fmt(fin)} con {holgura:.1f} h laborables de margen")
        provis = [of for of in ofs if of in provisional_of]
        if provis:
            motivos.append(f"{len(provis)} OF pendientes de programación (plan provisional)")
            if nivel == NivelRiesgo.VERDE:
                nivel = NivelRiesgo.AMARILLO
            acciones.append("Registrar los programas pendientes (LCH/LaserTub) para confirmar el plan")
        aparatos[ap_id] = {
            "aparato_id": ap_id,
            "referencia": ap.referencia,
            "tanda_id": ap.tanda_id,
            "nivel": nivel,
            "motivos": motivos,
            "fin_previsto": fin.isoformat() if fin else None,
            "holgura_h": None if holgura is None else round(holgura, 1),
            "horas_restantes": round(horas_rest, 1),
            "semana": ap.semana,
            "limite": ap.limite.isoformat() if ap.limite else None,
            "ofs_pendientes": len(ofs),
            "ofs_no_planificables": len(bloqueadas),
            "acciones": acciones,
        }

    # ---- Tandas
    tandas: dict[int, dict] = {}
    for t_id, t in inst.tandas.items():
        aps = [a for a in aparatos.values() if a["tanda_id"] == t_id]
        nivel = _peor([a["nivel"] for a in aps])
        motivos = []
        for a in sorted(aps, key=lambda a: -ORDEN_RIESGO[NivelRiesgo(a["nivel"])]):
            if a["nivel"] != NivelRiesgo.VERDE:
                motivos.append(f"Aparato {a['referencia']} ({a['nivel']}): {a['motivos'][0]}")
        horas = sum(a["horas_restantes"] for a in aps)
        fines = [a["fin_previsto"] for a in aps if a["fin_previsto"]]
        total = sum(inst.ops_totales_por_aparato.get(a["aparato_id"], 0) for a in aps)
        hecho = sum(inst.ops_terminadas_por_aparato.get(a["aparato_id"], 0) for a in aps)
        tandas[t_id] = {
            "tanda_id": t_id,
            "numero": t["numero"],
            "semana": t["semana"],
            "nivel": nivel,
            "motivos": motivos or ["Todos sus aparatos en plazo"],
            "aparatos": len(aps),
            "aparatos_en_riesgo": sum(1 for a in aps if a["nivel"] != NivelRiesgo.VERDE),
            "horas_restantes": round(horas, 1),
            "fin_previsto": max(fines) if fines else None,
            "progreso": round(hecho / total, 3) if total else 0.0,
        }
    return {"ofs": ofs_riesgo, "aparatos": aparatos, "tandas": tandas}
