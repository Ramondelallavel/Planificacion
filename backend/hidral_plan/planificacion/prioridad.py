"""Índice dinámico de prioridad con explicación (puntos 14 y 22).

Cada factor se normaliza a 0..1 y se pondera con los pesos configurables
"pesos_prioridad". El resultado no es solo un número: se devuelve la lista de motivos
en lenguaje de planta y la contribución de cada factor.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from .modelo import Instantanea, OpP

NOMBRES = {
    "holgura": "Holgura frente a la semana",
    "semana": "Cercanía de la semana de fabricación",
    "retraso": "Fuera de plazo",
    "sucesores": "OF que esperan por esta",
    "cierre_aparato": "Aparato casi completo",
    "cuello_botella": "Alimenta un cuello de botella",
    "prioridad_ortems": "Prioridad ORTEMS",
    "urgente": "Marcada urgente",
}


@dataclass
class Prioridad:
    valor: float
    factores: list[dict]
    motivos: list[str]
    holgura_h: float | None
    cadena_h: float
    limite: datetime | None
    horas_hasta_limite: float | None
    sucesoras: int
    datos_no_disponibles: list[str] = field(default_factory=list)

    def a_dict(self) -> dict:
        return {
            "valor": round(self.valor, 1),
            "factores": self.factores,
            "motivos": self.motivos,
            "holgura_h": None if self.holgura_h is None else round(self.holgura_h, 1),
            "cadena_pendiente_h": round(self.cadena_h, 1),
            "limite": self.limite.isoformat() if self.limite else None,
            "horas_laborables_hasta_limite": None if self.horas_hasta_limite is None else round(self.horas_hasta_limite, 1),
            "of_sucesoras": self.sucesoras,
            "datos_no_disponibles": self.datos_no_disponibles,
        }


def _cadena_aguas_abajo(inst: Instantanea) -> dict[int, float]:
    """Minutos de la cadena más larga que queda desde cada operación hasta el final (incluida)."""
    memo: dict[int, float] = {}
    en_curso: set[int] = set()

    def visitar(i: int) -> float:
        if i in memo:
            return memo[i]
        if i in en_curso:  # ciclo: se corta (ya se informa como dependencia circular)
            return 0.0
        en_curso.add(i)
        op = inst.ops[i]
        propio = max(0.0, (op.duracion or 0.0) - op.minutos_hechos)
        suc = [visitar(j) for j in inst.sucesoras_op(i) if j in inst.ops]
        en_curso.discard(i)
        memo[i] = propio + (max(suc) if suc else 0.0)
        return memo[i]

    import sys

    limite = sys.getrecursionlimit()
    sys.setrecursionlimit(max(limite, 20000))
    try:
        for i in inst.ops:
            visitar(i)
    finally:
        sys.setrecursionlimit(limite)
    return memo


def _sucesoras_of(inst: Instantanea) -> dict[int, int]:
    memo: dict[int, set[int]] = {}

    def visitar(of_id: int, pila: frozenset) -> set[int]:
        if of_id in memo:
            return memo[of_id]
        if of_id in pila:
            return set()
        total: set[int] = set()
        for s in inst.of_sucesoras.get(of_id, ()):
            total.add(s)
            total |= visitar(s, pila | {of_id})
        memo[of_id] = total
        return total

    return {of_id: len(visitar(of_id, frozenset())) for of_id in inst.of_ops}


def _progreso_aparato(inst: Instantanea, op: OpP) -> tuple[float, str | None]:
    mejor, ref = 0.0, None
    for ap in op.aparatos:
        total = inst.ops_totales_por_aparato.get(ap, 0.0)
        if total > 0:
            p = inst.ops_terminadas_por_aparato.get(ap, 0.0) / total
            if p >= mejor:
                mejor, ref = p, inst.aparatos[ap].referencia if ap in inst.aparatos else str(ap)
    return mejor, ref


def calcular_prioridades(inst: Instantanea, cuellos: set[int] | None = None, recursos_de_op: dict[int, list[int]] | None = None) -> dict[int, Prioridad]:
    pesos: dict[str, float] = inst.config["pesos_prioridad"]
    umbrales = inst.config["umbrales_riesgo"]
    escala_holgura = 2 * float(umbrales.get("amarillo_holgura_h", 24))
    cuellos = cuellos or set()
    recursos_de_op = recursos_de_op or {}
    cadena = _cadena_aguas_abajo(inst)
    sucesoras = _sucesoras_of(inst)
    max_suc = max(sucesoras.values(), default=0) or 1
    ortems = [o.prioridad_ortems for o in inst.ops.values() if o.prioridad_ortems is not None]
    o_min, o_max = (min(ortems), max(ortems)) if ortems else (0.0, 1.0)
    suma_pesos = sum(pesos.values()) or 1.0
    salida: dict[int, Prioridad] = {}

    for op in inst.ops.values():
        f: dict[str, float] = {}
        motivos: list[str] = []
        nd: list[str] = []
        tanda = inst.tandas.get(op.tanda_id or -1, {})
        if tanda:
            motivos.append(f"pertenece a la tanda {tanda.get('numero')}")
        if op.semana:
            motivos.append(f"semana de fabricación {op.semana}")
        else:
            nd.append("semana de fabricación")
        cad_h = cadena.get(op.id, 0.0) / 60
        horas = holgura = None
        if op.limite:
            inicio = max(filter(None, [inst.ahora, op.liberacion, op.release_externa]))
            horas = inst.horas_laborables(inicio, op.limite)
            holgura = horas - cad_h
            f["holgura"] = 1.0 if holgura <= 0 else max(0.0, 1 - holgura / escala_holgura)
            dias = (op.limite - inst.ahora).total_seconds() / 86400
            f["semana"] = min(1.0, max(0.0, 1 - dias / 21))
            f["retraso"] = 1.0 if inst.ahora > op.limite else 0.0
            if holgura <= 0:
                motivos.append(
                    f"quedan {horas:.1f} h laborables hasta el límite de la semana y la cadena pendiente desde esta OF suma {cad_h:.1f} h: NO hay holgura ({holgura:.1f} h)"
                )
            else:
                motivos.append(f"quedan {horas:.1f} h laborables hasta el límite y la cadena pendiente suma {cad_h:.1f} h (holgura {holgura:.1f} h)")
            if f["retraso"]:
                motivos.append("la semana de fabricación ya ha vencido")
        else:
            f["holgura"] = f["semana"] = f["retraso"] = 0.0
            nd.append("límite de semana (sin semana no se puede calcular la holgura)")
        n_suc = sucesoras.get(op.of_id, 0)
        f["sucesores"] = n_suc / max_suc
        if n_suc:
            motivos.append(f"{n_suc} OF posteriores dependen de esta (bloqueo aguas abajo)")
        prog, ref = _progreso_aparato(inst, op)
        f["cierre_aparato"] = prog
        if prog >= 0.5 and ref:
            motivos.append(f"el aparato {ref} está completado al {prog * 100:.0f}%: conviene cerrarlo")
        alimenta = [j for j in inst.sucesoras_op(op.id) if set(recursos_de_op.get(j, [])) and set(recursos_de_op.get(j, [])) <= cuellos]
        f["cuello_botella"] = 1.0 if alimenta else 0.0
        if alimenta:
            motivos.append("alimenta a un recurso cuello de botella: no dejarlo sin trabajo")
        if op.prioridad_ortems is not None:
            f["prioridad_ortems"] = (op.prioridad_ortems - o_min) / (o_max - o_min) if o_max > o_min else 1.0
            motivos.append(f"prioridad ORTEMS {op.prioridad_ortems:g}")
        else:
            f["prioridad_ortems"] = 0.0
        f["urgente"] = 1.0 if op.urgente else 0.0
        if op.urgente:
            motivos.append("marcada URGENTE por un responsable")
        if holgura is not None and 0 < holgura < escala_holgura:
            motivos.append(f"si se retrasa más de {holgura:.1f} h laborables compromete la semana {op.semana}")
        valor = 100 * sum(pesos.get(k, 0) * v for k, v in f.items()) / suma_pesos
        factores = sorted(
            (
                {"factor": k, "nombre": NOMBRES.get(k, k), "valor": round(v, 3), "peso": pesos.get(k, 0), "contribucion": round(100 * pesos.get(k, 0) * v / suma_pesos, 1)}
                for k, v in f.items()
            ),
            key=lambda x: -x["contribucion"],
        )
        salida[op.id] = Prioridad(valor, factores, motivos, holgura, cad_h, op.limite, horas, n_suc, nd)
    return salida
