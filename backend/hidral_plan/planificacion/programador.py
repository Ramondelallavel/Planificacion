"""Programador con restricciones (APS de capacidad finita).

Restricciones DURAS (nunca se violan):
  * recurso capaz: misma sección, tipo de operación admitido, máquina citada en el programa;
  * operario cualificado para ese recurso/operación y dentro de su turno, sin ausencias;
  * precedencias: dentro de la OF (secuencia) y entre OF (grafo de dependencias);
  * recurso sin avería/parada y sin otro trabajo en el mismo tramo;
  * material: si la OF está marcada sin material y sin fecha, no se planifica;
  * programación: la operación de máquina va siempre después de la de programación.
Restricciones BLANDAS (desempate configurable): agrupar misma familia de setup (material /
programa) en la misma máquina y equilibrar carga entre recursos y operarios.

Algoritmo: generación en serie de la programación (serial SGS) guiada por el índice de
prioridad; cada operación se coloca en el primer hueco factible (con "backfilling"),
eligiendo la combinación recurso/operario que termina antes.
"""

from __future__ import annotations

import heapq
import math
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from .calendario import Ocupacion, Ventanas, interseccion, repartir
from .modelo import AsigP, Instantanea, OperarioP, OpP, RecursoP
from .prioridad import Prioridad, calcular_prioridades


@dataclass
class NoPlanificada:
    op_id: int
    of_id: int
    of_numero: str
    tipo: str
    motivo: str
    detalle: str

    def a_dict(self) -> dict:
        return {"operacion_id": self.op_id, "of_id": self.of_id, "of": self.of_numero, "tipo": self.tipo, "motivo": self.motivo, "detalle": self.detalle}


@dataclass
class ResultadoProgramacion:
    asignaciones: dict[int, AsigP]
    no_planificadas: dict[int, NoPlanificada]
    prioridades: dict[int, Prioridad]
    cuellos_previstos: set[int] = field(default_factory=set)
    fin_virtual: dict[int, datetime] = field(default_factory=dict)


def candidatos(inst: Instantanea, op: OpP) -> list[RecursoP]:
    return [r for r in inst.recursos.values() if r.puede(op)]


def recursos_por_op(inst: Instantanea) -> dict[int, list[int]]:
    return {op.id: [r.id for r in candidatos(inst, op)] for op in inst.ops.values()}


def preanalisis_cuellos(inst: Instantanea, rec_op: dict[int, list[int]]) -> set[int]:
    """Recursos cuya demanda (repartida entre alternativas) supera el umbral de utilización
    hasta el límite más lejano de las operaciones que pueden hacer."""
    umbral = float(inst.config["umbrales_riesgo"].get("utilizacion_cuello_botella", 0.85))
    demanda: dict[int, float] = {}
    limite: dict[int, datetime] = {}
    for op in inst.ops.values():
        rs = rec_op.get(op.id, [])
        if not rs or not op.duracion:
            continue
        for r in rs:
            demanda[r] = demanda.get(r, 0.0) + op.duracion / len(rs)
            if op.limite:
                limite[r] = max(limite.get(r, op.limite), op.limite)
    cuellos: set[int] = set()
    for r, d in demanda.items():
        rec = inst.recursos[r]
        hasta = min(limite.get(r, inst.horizonte), inst.horizonte)
        cap = inst.ventanas_recurso(rec).minutos(inst.ahora, hasta) * rec.capacidad
        if cap <= 0 or d / cap >= umbral:
            cuellos.add(r)
    return cuellos


def _ventanas_combinadas(inst: Instantanea, r: RecursoP, o: OperarioP | None) -> Ventanas:
    if o is None:
        return inst.ventanas_recurso(r)
    clave = ("RO", r.id, tuple(r.paradas), o.id, tuple(o.ausencias))
    cache = inst._ventanas_cache
    if clave not in cache:
        cache[clave] = Ventanas(interseccion(inst.ventanas_recurso(r).lista, inst.ventanas_operario(o).lista))
    return cache[clave]


def _buscar_hueco(vent: Ventanas, desde: datetime, minutos: float, ocupaciones: list[Ocupacion]) -> tuple[list | None, tuple | None]:
    """Primer inicio >= desde en que la operación cabe entera sin solapar trabajo ya asignado.
    Devuelve (tramos, último conflicto encontrado)."""
    t = desde
    ultimo_conflicto = None
    for _ in range(5000):
        ini = vent.siguiente_inicio(t)
        if ini is None:
            return None, ultimo_conflicto
        tramos = repartir(vent, ini, minutos)
        if tramos is None:
            return None, ultimo_conflicto
        conflicto = None
        for oc in ocupaciones:
            c = oc.primer_conflicto(tramos)
            if c is not None and (conflicto is None or c[1] > conflicto[1][1]):
                conflicto = (oc, c)
        if conflicto is None:
            return tramos, ultimo_conflicto
        ultimo_conflicto = (conflicto[0], conflicto[1], conflicto[0].id_en(conflicto[1]))
        t = conflicto[1][1]
    return None, ultimo_conflicto


def _fmt(d: datetime) -> str:
    return d.strftime("%d/%m %H:%M")


class Programador:
    def __init__(self, inst: Instantanea, prioridades: dict[int, Prioridad] | None = None) -> None:
        self.inst = inst
        self.rec_op = recursos_por_op(inst)
        self.cuellos = preanalisis_cuellos(inst, self.rec_op)
        self.prioridades = prioridades or calcular_prioridades(inst, self.cuellos, self.rec_op)
        self.obj = inst.config["objetivos_plan"]
        self.params = inst.config["planificacion"]
        self.oc_rec: dict[tuple[int, int], Ocupacion] = {}
        self.oc_op: dict[int, Ocupacion] = {}
        self.carga_rec: dict[int, float] = {}
        self.carga_op: dict[int, float] = {}
        self.asign: dict[int, AsigP] = {}
        self.fin_virtual: dict[int, datetime] = {}

    # ---------------------------------------------------------------- ocupación
    def _ocup_rec(self, rid: int, unidad: int) -> Ocupacion:
        return self.oc_rec.setdefault((rid, unidad), Ocupacion())

    def _ocup_op(self, oid: int) -> Ocupacion:
        return self.oc_op.setdefault(oid, Ocupacion())

    def registrar(self, a: AsigP) -> None:
        self.asign[a.op_id] = a
        if a.recurso_id is not None:
            self._ocup_rec(a.recurso_id, a.unidad).agregar(a.tramos, a.op_id)
            self.carga_rec[a.recurso_id] = self.carga_rec.get(a.recurso_id, 0.0) + a.minutos
        if a.operario_id is not None:
            self._ocup_op(a.operario_id).agregar(a.tramos, a.op_id)
            self.carga_op[a.operario_id] = self.carga_op.get(a.operario_id, 0.0) + a.minutos

    # ---------------------------------------------------------------- validaciones previas
    def motivo_no_planificable(self, op: OpP) -> tuple[str, str] | None:
        if op.bloqueada:
            return "BLOQUEADA", f"La OF {op.of_numero} está bloqueada manualmente."
        if op.material_bloqueado:
            return "ESPERANDO_MATERIAL", f"OF {op.of_numero}: material no disponible y sin fecha prevista (DATO NO DISPONIBLE)."
        if op.bloqueos_externos:
            return "PREDECESORA_EXTERNA", f"Espera a OF {', '.join(op.bloqueos_externos)} fuera de este plan y sin fecha prevista de disponibilidad."
        rs = [self.inst.recursos[r] for r in self.rec_op.get(op.id, [])]
        if not rs:
            detalle = f"sección {op.seccion or '?'}, operación {op.tipo}"
            if op.recurso_preferido:
                detalle += f", máquina {op.recurso_preferido} indicada en el programa"
            extra = (
                ""
                if op.tiene_hoja
                else " OF referenciada sin hoja: informe su fecha prevista de disponibilidad (ORTEMS/MRP o manual) para poder planificar lo que depende de ella."
            )
            return "SIN_RECURSO", f"Ningún recurso configurado/operativo puede hacerla ({detalle}).{extra}"
        if op.duracion is None:
            return "SIN_DURACION", f"OF {op.of_numero} ({op.tipo}): duración DATO NO DISPONIBLE (sin tiempo estándar)."
        if op.pendiente_programa and not self.params.get("planificar_pendiente_programacion", True):
            return "PENDIENTE_PROGRAMACION", f"OF {op.of_numero}: pendiente de programación; no se asigna a máquina hasta que exista el programa."
        if all(r.requiere_operario for r in rs) and not any(o.cualificado(r, op) for r in rs for o in self.inst.operarios.values()):
            return "SIN_OPERARIO", f"Ningún operario cualificado para {', '.join(r.codigo for r in rs)}."
        return None

    # ---------------------------------------------------------------- colocación
    def colocar(self, op: OpP) -> AsigP | None | tuple[str, str]:
        inst = self.inst
        condiciones: list[str] = []
        desde = inst.ahora
        motivo_desde = "ahora"
        for p in op.predecesoras:
            fin = self.asign[p].fin if p in self.asign else self.fin_virtual.get(p)
            if fin and fin > desde:
                desde = fin
                pred = inst.ops.get(p)
                motivo_desde = f"espera a la OF {pred.of_numero} ({pred.tipo}) que termina el {_fmt(fin)}" if pred else f"espera a una operación previa hasta {_fmt(fin)}"
        for fecha, texto in ((op.liberacion, "material disponible desde"), (op.release_externa, "OF externa disponible desde")):
            if fecha and fecha > desde:
                desde, motivo_desde = fecha, f"{texto} {_fmt(fecha)}"
        if motivo_desde != "ahora":
            condiciones.append(motivo_desde)
        minutos = float(math.ceil(max(0.0, (op.duracion or 0.0) - op.minutos_hechos)))  # el plan trabaja en minutos enteros
        bonus_setup = float(self.obj.get("minutos_bonificacion_setup", 20)) * float(self.obj.get("agrupar_setup", 0.6))
        w_carga = float(self.obj.get("equilibrar_carga", 0.3))
        opciones = []
        rechazos: list[str] = []
        for r in (inst.recursos[i] for i in self.rec_op.get(op.id, [])):
            operarios: list[OperarioP | None]
            if r.requiere_operario:
                operarios = [o for o in inst.operarios.values() if o.cualificado(r, op)]
                if not operarios:
                    rechazos.append(f"{r.codigo}: sin operario cualificado")
                    continue
            else:
                operarios = [None]
            for u in range(r.capacidad):
                for o in operarios:
                    vent = _ventanas_combinadas(inst, r, o)
                    ocs = [self._ocup_rec(r.id, u)] + ([self._ocup_op(o.id)] if o else [])
                    tramos, conflicto = _buscar_hueco(vent, desde, minutos, ocs)
                    if tramos is None:
                        rechazos.append(f"{r.codigo}{'/' + o.codigo if o else ''}: sin hueco en el horizonte")
                        continue
                    fin = tramos[-1][1]
                    anterior = self._ocup_rec(r.id, u).anterior_id(tramos[0][0])
                    mismo_setup = bool(anterior is not None and op.familia and inst.ops.get(anterior) and inst.ops[anterior].familia == op.familia)
                    puntuacion = fin.timestamp() / 60
                    if mismo_setup and (op.limite is None or fin <= op.limite):
                        puntuacion -= bonus_setup
                    puntuacion += w_carga * (self.carga_rec.get(r.id, 0.0) + (self.carga_op.get(o.id, 0.0) if o else 0.0)) / 60
                    opciones.append((puntuacion, fin, r, u, o, tramos, conflicto, mismo_setup, anterior))
        if not opciones:
            return ("SIN_HUECO", "; ".join(rechazos) or "sin combinación recurso/operario disponible")
        opciones.sort(key=lambda x: (x[0], x[2].codigo, x[4].codigo if x[4] else ""))
        _, fin, r, u, o, tramos, conflicto, mismo_setup, anterior = opciones[0]
        if tramos[0][0] > desde:
            if conflicto is not None:
                ident = conflicto[2]
                otra = inst.ops.get(ident) if ident is not None else None
                quien = f"la OF {otra.of_numero}" if otra else "otro trabajo"
                condiciones.append(f"{r.codigo if conflicto[0] in self.oc_rec.values() else (o.codigo if o else r.codigo)} ocupado por {quien} hasta {_fmt(conflicto[1][1])}")
            else:
                condiciones.append(f"fuera de turno/ventana laborable hasta {_fmt(tramos[0][0])}")
        explic = {
            "prioridad": self.prioridades[op.id].a_dict() if op.id in self.prioridades else None,
            "inicio_condicionado_por": condiciones or ["disponible inmediatamente"],
            "recurso": {
                "codigo": r.codigo,
                "motivo": (
                    f"máquina indicada en el programa ({op.recurso_preferido})"
                    if op.recurso_preferido
                    else ("único recurso capaz" if len(self.rec_op.get(op.id, [])) == 1 else f"de {len(self.rec_op[op.id])} recursos capaces, es el que termina antes")
                ),
            },
            "operario": {"codigo": o.codigo, "nombre": o.nombre, "motivo": f"cualificado para {r.codigo}, turno {o.turno}"} if o else None,
            "alternativas": [{"recurso": x[2].codigo, "operario": x[4].codigo if x[4] else None, "fin": x[1].isoformat()} for x in opciones[1:4]],
            "setup": (f"misma familia ({op.familia}) que el trabajo anterior en {r.codigo}: se evita un cambio de preparación" if mismo_setup else None),
            "provisional": (
                "Pendiente de programación: planificada tras la operación de programación; no podrá iniciarse hasta registrar el programa." if op.pendiente_programa else None
            ),
            "cuello_botella": r.id in self.cuellos,
        }
        return AsigP(
            op_id=op.id,
            of_id=op.of_id,
            recurso_id=r.id,
            unidad=u,
            operario_id=o.id if o else None,
            inicio=tramos[0][0],
            fin=fin,
            tramos=tramos,
            minutos=round(minutos, 1),
            prioridad=round(self.prioridades[op.id].valor, 1) if op.id in self.prioridades else None,
            explicacion=explic,
            provisional=op.pendiente_programa,
        )

    # ---------------------------------------------------------------- bucle principal
    def ejecutar(self, objetivo: set[int] | None = None, fijas: list[AsigP] | None = None) -> ResultadoProgramacion:
        inst = self.inst
        for a in fijas if fijas is not None else inst.fijas:
            self.registrar(a)
        objetivo = set(objetivo) if objetivo is not None else set(inst.ops) - set(self.asign)
        objetivo -= set(self.asign)
        no_plan: dict[int, NoPlanificada] = {}
        for i in sorted(objetivo):
            op = inst.ops[i]
            m = self.motivo_no_planificable(op)
            if m:
                if op.disponible_externo and m[0] in ("SIN_RECURSO", "SIN_DURACION", "SIN_OPERARIO"):
                    # OF gestionada fuera de este sistema con fecha prevista informada
                    self.fin_virtual[i] = op.disponible_externo
                    continue
                no_plan[i] = NoPlanificada(i, op.of_id, op.of_numero, op.tipo, m[0], m[1])
        objetivo -= set(no_plan) | set(self.fin_virtual)
        # propagación: si una predecesora no se puede planificar, la sucesora tampoco (sin suponer fechas)
        cambiado = True
        while cambiado:
            cambiado = False
            for i in sorted(objetivo):
                op = inst.ops[i]
                malas = [p for p in op.predecesoras if p in no_plan]
                if malas:
                    p = inst.ops[malas[0]]
                    no_plan[i] = NoPlanificada(
                        i,
                        op.of_id,
                        op.of_numero,
                        op.tipo,
                        "PREDECESORA_NO_PLANIFICABLE",
                        f"Espera a la OF {p.of_numero} ({p.tipo}), que no se puede planificar: {no_plan[malas[0]].detalle}",
                    )
                    objetivo.discard(i)
                    cambiado = True
        pendientes = {i: sum(1 for p in inst.ops[i].predecesoras if p in objetivo) for i in objetivo}
        heap = [(-self.prioridades[i].valor, inst.ops[i].limite or datetime.max, i) for i, n in pendientes.items() if n == 0]
        heapq.heapify(heap)
        colocadas: set[int] = set()

        def liberar_sucesoras(i: int) -> None:
            pila = [i]
            while pila:
                k = pila.pop()
                for j in inst.sucesoras_op(k):
                    if j not in pendientes or j in no_plan:
                        continue
                    pendientes[j] -= 1
                    if pendientes[j] > 0:
                        continue
                    fallidas = [p for p in inst.ops[j].predecesoras if p in no_plan]
                    if fallidas:
                        # una predecesora no se pudo colocar: la sucesora tampoco (sin suponer fechas)
                        oj, op_f = inst.ops[j], inst.ops[fallidas[0]]
                        no_plan[j] = NoPlanificada(
                            j, oj.of_id, oj.of_numero, oj.tipo, "PREDECESORA_NO_PLANIFICABLE", f"Espera a la OF {op_f.of_numero} ({op_f.tipo}), que no se ha podido planificar."
                        )
                        pila.append(j)
                    else:
                        heapq.heappush(heap, (-self.prioridades[j].valor, inst.ops[j].limite or datetime.max, j))

        while heap:
            _, _, i = heapq.heappop(heap)
            op = inst.ops[i]
            res = self.colocar(op)
            if isinstance(res, AsigP):
                self.registrar(res)
                colocadas.add(i)
            else:
                no_plan[i] = NoPlanificada(i, op.of_id, op.of_numero, op.tipo, res[0], res[1])
            liberar_sucesoras(i)
        for i in objetivo - colocadas - set(no_plan):
            op = inst.ops[i]
            no_plan[i] = NoPlanificada(
                i, op.of_id, op.of_numero, op.tipo, "DEPENDENCIA_CIRCULAR_O_BLOQUEO", "No se ha podido ordenar: dependencia circular o predecesora no planificada."
            )
        return ResultadoProgramacion(self.asign, no_plan, self.prioridades, self.cuellos, self.fin_virtual)


def programar(inst: Instantanea, objetivo: set[int] | None = None, fijas: list[AsigP] | None = None, prioridades: dict[int, Prioridad] | None = None) -> ResultadoProgramacion:
    return Programador(inst, prioridades).ejecutar(objetivo, fijas)


def tramos_json(tramos: list) -> list[list[str]]:
    return [[a.isoformat(), b.isoformat()] for a, b in tramos]


def desplazar(a: AsigP, minutos: float) -> AsigP:
    d = timedelta(minutes=minutos)
    return AsigP(
        a.op_id,
        a.of_id,
        a.recurso_id,
        a.unidad,
        a.operario_id,
        a.inicio + d,
        a.fin + d,
        [(x + d, y + d) for x, y in a.tramos],
        a.minutos,
        a.prioridad,
        a.explicacion,
        a.provisional,
        a.fija,
    )
