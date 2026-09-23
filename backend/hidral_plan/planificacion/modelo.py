"""Instantánea de planificación en memoria.

El programador trabaja sobre estas estructuras (no sobre la BD): así el mismo código sirve
para el plan oficial, la replanificación incremental y las simulaciones what-if, que
modifican una copia sin tocar producción.
"""

from __future__ import annotations

import copy
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import configuracion
from ..ingesta.normalizacion import limites_semana
from ..modelos import (
    Aparato,
    AsignacionPlan,
    Ausencia,
    DependenciaOF,
    Festivo,
    Fichaje,
    JornadaExtra,
    OFAparato,
    Operacion,
    Operario,
    OrdenFabricacion,
    ParadaRecurso,
    Plan,
    Recurso,
    Tanda,
    Turno,
)
from ..modelos.enums import (
    ESTADOS_OF_CERRADOS,
    EstadoOperacion,
    EstadoPlan,
    EstadoRecurso,
    TipoPlan,
)
from .calendario import Intervalo, TurnoDef, Ventanas, fusionar, restar, turno_desde_modelo, ventanas_turno


@dataclass
class OpP:
    id: int
    of_id: int
    of_numero: str
    tipo: str
    seccion: str | None
    duracion: float | None
    estado: str
    secuencia: int
    predecesoras: set[int] = field(default_factory=set)
    recurso_preferido: str | None = None
    requiere_programa: bool = False
    pendiente_programa: bool = False
    familia: str | None = None
    liberacion: datetime | None = None
    material_bloqueado: bool = False
    bloqueada: bool = False
    urgente: bool = False
    prioridad_ortems: float | None = None
    semana: str | None = None
    limite: datetime | None = None
    aparatos: list[int] = field(default_factory=list)
    tanda_id: int | None = None
    grupo_hf: str | None = None
    descripcion: str | None = None
    cantidad: float | None = None
    minutos_hechos: float = 0.0
    disponible_externo: datetime | None = None  # OF gestionada fuera: disponible en esta fecha
    tiene_hoja: bool = True
    bloqueos_externos: list[str] = field(default_factory=list)  # OF predecesoras fuera del plan sin fecha
    release_externa: datetime | None = None  # fecha de disponibilidad de predecesoras externas


@dataclass
class RecursoP:
    id: int
    codigo: str
    nombre: str
    seccion: str | None
    tipo: str
    capacidad: int
    operaciones: list[str] | None
    turnos: list[str] | None
    requiere_operario: bool
    estado: str
    paradas: list[Intervalo] = field(default_factory=list)
    restricciones: dict | None = None

    def puede(self, op: OpP) -> bool:
        if self.estado != EstadoRecurso.OPERATIVO and not self.paradas:
            # averiado sin fecha de fin conocida: no disponible
            return False
        if op.seccion != self.seccion:
            return False
        if op.recurso_preferido and op.recurso_preferido != self.codigo:
            return False
        if (op.tipo == "PROGRAMACION") != (self.tipo == "PROGRAMACION"):
            return False
        return not self.operaciones or op.tipo in self.operaciones


@dataclass
class OperarioP:
    id: int
    codigo: str
    nombre: str
    turno: str | None
    recursos: set[str]
    tipos: set[str]
    ausencias: list[Intervalo] = field(default_factory=list)

    def cualificado(self, recurso: RecursoP, op: OpP) -> bool:
        return recurso.codigo in self.recursos or op.tipo in self.tipos


@dataclass
class AsigP:
    op_id: int
    of_id: int
    recurso_id: int | None
    unidad: int
    operario_id: int | None
    inicio: datetime
    fin: datetime
    tramos: list[Intervalo]
    minutos: float
    prioridad: float | None = None
    explicacion: dict | None = None
    provisional: bool = False
    fija: bool = False  # en curso o bloqueada por el usuario: no se mueve


@dataclass
class AparatoP:
    id: int
    referencia: str
    tanda_id: int
    semana: str | None
    limite: datetime | None


@dataclass
class Instantanea:
    ahora: datetime
    horizonte: datetime
    ops: dict[int, OpP]
    recursos: dict[int, RecursoP]
    operarios: dict[int, OperarioP]
    turnos: dict[str, TurnoDef]
    festivos: set[date]
    aparatos: dict[int, AparatoP]
    tandas: dict[int, dict]
    of_numeros: dict[int, str]
    of_ops: dict[int, list[int]]
    of_sucesoras: dict[int, set[int]]
    of_predecesoras: dict[int, set[int]]
    fijas: list[AsigP]
    config: dict
    ops_terminadas_por_aparato: dict[int, float] = field(default_factory=dict)
    ops_totales_por_aparato: dict[int, float] = field(default_factory=dict)
    # jornadas extra: (fecha, turno, secciones o None = toda la fábrica)
    extras: list[tuple[date, str, frozenset[str] | None]] = field(default_factory=list)
    _ventanas_cache: dict = field(default_factory=dict, repr=False)

    def copia(self) -> Instantanea:
        c = copy.deepcopy(self)
        c._ventanas_cache = {}
        return c

    def dias_extra(self, turno: str, secciones: set[str | None] | None) -> set[date]:
        """Días de jornada extra de `turno` que afectan a alguna de `secciones` (None: solo las de toda la fábrica)."""
        return {f for f, t, secs in self.extras if t == turno and (secs is None or (secciones is not None and secs & secciones))}

    def ventanas_recurso(self, r: RecursoP) -> Ventanas:
        clave = ("R", r.id, tuple(r.paradas), tuple(self.extras))
        if clave not in self._ventanas_cache:
            base: list[Intervalo] = []
            for t in r.turnos or list(self.turnos):
                if t in self.turnos:
                    base += ventanas_turno(self.turnos[t], self.ahora, self.horizonte, self.festivos, self.dias_extra(t, {r.seccion}))
            self._ventanas_cache[clave] = Ventanas(restar(fusionar(base), r.paradas))
        return self._ventanas_cache[clave]

    def ventanas_operario(self, o: OperarioP) -> Ventanas:
        clave = ("O", o.id, tuple(o.ausencias), tuple(self.extras))
        if clave not in self._ventanas_cache:
            # el operario hace la jornada extra de las secciones de las máquinas en que está cualificado
            secciones = {r.seccion for r in self.recursos.values() if r.codigo in o.recursos}
            base = ventanas_turno(self.turnos[o.turno], self.ahora, self.horizonte, self.festivos, self.dias_extra(o.turno, secciones)) if o.turno in self.turnos else []
            self._ventanas_cache[clave] = Ventanas(restar(base, o.ausencias))
        return self._ventanas_cache[clave]

    def ventanas_fabrica(self) -> Ventanas:
        if "F" not in self._ventanas_cache:
            base: list[Intervalo] = []
            for c, t in self.turnos.items():
                base += ventanas_turno(t, self.ahora - timedelta(days=1), self.horizonte + timedelta(days=60), self.festivos, self.dias_extra(c, None))
            self._ventanas_cache["F"] = Ventanas(fusionar(base))
        return self._ventanas_cache["F"]

    def horas_laborables(self, desde: datetime, hasta: datetime) -> float:
        if hasta <= desde:
            return -self.ventanas_fabrica().minutos(hasta, desde) / 60
        return self.ventanas_fabrica().minutos(desde, hasta) / 60

    def sucesoras_op(self, op_id: int) -> list[int]:
        """Operaciones que tienen a op_id como predecesora (se calcula bajo demanda)."""
        if "_suc" not in self._ventanas_cache:
            suc: dict[int, list[int]] = defaultdict(list)
            for o in self.ops.values():
                for p in o.predecesoras:
                    suc[p].append(o.id)
            self._ventanas_cache["_suc"] = suc
        return self._ventanas_cache["_suc"].get(op_id, [])

    def invalidar_indices(self) -> None:
        self._ventanas_cache.pop("_suc", None)


def limite_semana(codigo: str | None, cfg: dict) -> datetime | None:
    if not codigo:
        return None
    lunes, _ = limites_semana(codigo)
    h, m = (int(x) for x in cfg.get("hora_limite", "23:59").split(":"))
    return lunes + timedelta(days=int(cfg.get("dia_limite", 4)), hours=h, minutes=m)


def cargar_instantanea(s: Session, ahora: datetime, tanda_ids: list[int] | None = None, incluir_bloqueadas_plan: bool = True) -> Instantanea:
    cfg = {k: configuracion.obtener(s, k) for k in configuracion.DEFECTOS}
    horizonte = ahora + timedelta(days=int(cfg["planificacion"].get("horizonte_dias", 21)))
    turnos = {t.codigo: turno_desde_modelo(t) for t in s.scalars(select(Turno).where(Turno.activo.is_(True)))}
    festivos = {f.fecha for f in s.scalars(select(Festivo))}
    extras = [
        (j.fecha, j.turno_codigo, frozenset(j.secciones) if j.secciones else None)
        for j in s.scalars(select(JornadaExtra).where(JornadaExtra.fecha >= ahora.date() - timedelta(days=1), JornadaExtra.fecha <= horizonte.date()).order_by(JornadaExtra.fecha))
    ]

    q_tandas = select(Tanda).where(Tanda.estado == "ACTIVA", Tanda.incluida_en_plan.is_(True))
    if tanda_ids:
        q_tandas = select(Tanda).where(Tanda.id.in_(tanda_ids))
    tandas = {t.id: {"numero": t.numero, "semana": t.semana_codigo, "producto": t.producto} for t in s.scalars(q_tandas)}
    ofs = list(s.scalars(select(OrdenFabricacion).where(OrdenFabricacion.tanda_id.in_(list(tandas)))))
    aparatos = {
        a.id: AparatoP(a.id, a.referencia, a.tanda_id, a.semana_codigo, limite_semana(a.semana_codigo, cfg["semana_fabricacion"]))
        for a in s.scalars(select(Aparato).where(Aparato.tanda_id.in_(list(tandas))))
    }
    of_aparatos: dict[int, list[int]] = defaultdict(list)
    for of_id, ap_id in s.execute(select(OFAparato.of_id, OFAparato.aparato_id).where(OFAparato.of_id.in_([o.id for o in ofs]))):
        of_aparatos[of_id].append(ap_id)

    of_pred: dict[int, set[int]] = defaultdict(set)
    of_suc: dict[int, set[int]] = defaultdict(set)
    todos_ids = {o.id for o in ofs}
    for o, d in s.execute(select(DependenciaOF.of_origen_id, DependenciaOF.of_destino_id).where(DependenciaOF.activa.is_(True), DependenciaOF.of_destino_id.in_(list(todos_ids)))):
        of_pred[d].add(o)
        of_suc[o].add(d)

    ops: dict[int, OpP] = {}
    of_ops: dict[int, list[int]] = defaultdict(list)
    of_por_id = {o.id: o for o in ofs}
    terminadas_por_aparato: dict[int, float] = defaultdict(float)
    totales_por_aparato: dict[int, float] = defaultdict(float)
    for op in s.scalars(select(Operacion).where(Operacion.of_id.in_([o.id for o in ofs])).order_by(Operacion.of_id, Operacion.secuencia)):
        of = of_por_id[op.of_id]
        for ap in of_aparatos.get(of.id, []):
            reparto = (op.duracion_estimada_min or 0) / max(1, len(of_aparatos[of.id]))
            totales_por_aparato[ap] += reparto
            if op.estado == EstadoOperacion.TERMINADA:
                terminadas_por_aparato[ap] += reparto
        if op.estado == EstadoOperacion.TERMINADA or of.estado in ESTADOS_OF_CERRADOS:
            continue
        limites = [aparatos[a].limite for a in of_aparatos.get(of.id, []) if a in aparatos and aparatos[a].limite]
        limite = min(limites) if limites else limite_semana(of.semana_codigo, cfg["semana_fabricacion"])
        ops[op.id] = OpP(
            id=op.id,
            of_id=of.id,
            of_numero=of.numero,
            tipo=op.tipo,
            seccion=op.seccion_codigo,
            duracion=op.duracion_estimada_min,
            estado=op.estado,
            secuencia=op.secuencia,
            recurso_preferido=op.recurso_preferido,
            requiere_programa=op.requiere_programa,
            pendiente_programa=op.estado == EstadoOperacion.PENDIENTE_PROGRAMACION,
            familia=op.familia_setup,
            liberacion=of.material_disponible_desde,
            material_bloqueado=of.material_disponible is False and of.material_disponible_desde is None,
            bloqueada=of.bloqueada_manual,
            urgente=of.urgente,
            prioridad_ortems=of.prioridad_ortems,
            semana=of.semana_codigo,
            limite=limite,
            aparatos=of_aparatos.get(of.id, []),
            tanda_id=of.tanda_id,
            grupo_hf=of.grupo_hf,
            descripcion=of.descripcion,
            cantidad=op.cantidad,
            minutos_hechos=0.0,
            disponible_externo=of.disponible_prevista,
            tiene_hoja=of.tiene_hoja,
        )
        of_ops[of.id].append(op.id)
    # Precedencias: dentro de la OF por secuencia; entre OF, primera op de la sucesora tras la última de la predecesora
    for lista in of_ops.values():
        lista.sort(key=lambda i: ops[i].secuencia)
        for a, b in zip(lista, lista[1:], strict=False):
            ops[b].predecesoras.add(a)
    externas: set[int] = set()
    for of_id, lista in of_ops.items():
        primera = ops[lista[0]]
        for pred_of in of_pred.get(of_id, ()):
            if of_ops.get(pred_of):
                primera.predecesoras.add(of_ops[pred_of][-1])
            elif pred_of not in of_por_id:
                externas.add(pred_of)
    if externas:
        # predecesoras de otras tandas no incluidas en el plan: si no están cerradas y no hay
        # fecha prevista, la sucesora no puede planificarse (no se supone que estarán listas)
        info = {o.id: o for o in s.scalars(select(OrdenFabricacion).where(OrdenFabricacion.id.in_(list(externas))))}
        for of_id, lista in of_ops.items():
            primera = ops[lista[0]]
            for pred_of in of_pred.get(of_id, ()):
                o = info.get(pred_of)
                if o is None or o.estado in ESTADOS_OF_CERRADOS:
                    continue
                if o.disponible_prevista:
                    primera.release_externa = max(filter(None, [primera.release_externa, o.disponible_prevista]))
                else:
                    primera.bloqueos_externos.append(o.numero)

    recursos: dict[int, RecursoP] = {}
    paradas: dict[int, list[Intervalo]] = defaultdict(list)
    for p in s.scalars(select(ParadaRecurso).where((ParadaRecurso.fin.is_(None)) | (ParadaRecurso.fin > ahora))):
        paradas[p.recurso_id].append((max(p.inicio, ahora - timedelta(days=1)), p.fin or horizonte + timedelta(days=365)))
    for r in s.scalars(select(Recurso).where(Recurso.activo.is_(True))):
        recursos[r.id] = RecursoP(
            r.id,
            r.codigo,
            r.nombre,
            r.seccion_codigo,
            r.tipo,
            max(1, r.capacidad),
            r.operaciones,
            r.turnos,
            r.requiere_operario,
            r.estado,
            fusionar(paradas.get(r.id, [])),
            r.restricciones,
        )
        if r.estado != EstadoRecurso.OPERATIVO and not paradas.get(r.id):
            recursos[r.id].paradas = [(ahora - timedelta(days=1), horizonte + timedelta(days=365))]
    ausencias: dict[int, list[Intervalo]] = defaultdict(list)
    for a in s.scalars(select(Ausencia).where((Ausencia.fin.is_(None)) | (Ausencia.fin > ahora))):
        ausencias[a.operario_id].append((a.inicio, a.fin or horizonte + timedelta(days=365)))
    operarios: dict[int, OperarioP] = {}
    for o in s.scalars(select(Operario).where(Operario.activo.is_(True))):
        operarios[o.id] = OperarioP(
            o.id,
            o.codigo_empleado,
            o.nombre,
            o.turno_codigo,
            {c.recurso_codigo for c in o.cualificaciones if c.recurso_codigo},
            {c.tipo_operacion for c in o.cualificaciones if c.tipo_operacion},
            fusionar(ausencias.get(o.id, [])),
        )

    # Asignaciones fijas: operaciones en curso (fichaje abierto) y bloqueadas por el usuario en el plan activo
    fijas: list[AsigP] = []
    en_curso = {f.operacion_id: f for f in s.scalars(select(Fichaje).where(Fichaje.estado.in_(["ABIERTO", "PAUSADO"])))}
    plan = s.scalar(select(Plan).where(Plan.tipo == TipoPlan.OFICIAL, Plan.estado == EstadoPlan.ACTIVO).order_by(Plan.id.desc()))
    asig_plan = {a.operacion_id: a for a in s.scalars(select(AsignacionPlan).where(AsignacionPlan.plan_id == plan.id))} if plan else {}
    for op_id, op in ops.items():
        f = en_curso.get(op_id)
        if f is not None:
            hecho = (ahora - f.inicio).total_seconds() / 60 - (f.minutos_pausa or 0)
            op.minutos_hechos = max(0.0, hecho)
            restante = max(1.0, (op.duracion or hecho) - hecho)
            fin = ahora + timedelta(minutes=restante)
            fijas.append(
                AsigP(
                    op_id, op.of_id, f.recurso_id, 0, f.operario_id, ahora, fin, [(ahora, fin)], restante, fija=True, explicacion={"motivo": "Operación en curso (fichaje abierto)"}
                )
            )
        elif incluir_bloqueadas_plan and op_id in asig_plan and asig_plan[op_id].bloqueada:
            a = asig_plan[op_id]
            tramos = [(datetime.fromisoformat(x[0]), datetime.fromisoformat(x[1])) for x in (a.segmentos or [[a.inicio.isoformat(), a.fin.isoformat()]])]
            fijas.append(AsigP(op_id, op.of_id, a.recurso_id, a.unidad, a.operario_id, a.inicio, a.fin, tramos, a.minutos, a.prioridad, a.explicacion, a.provisional, fija=True))

    return Instantanea(
        ahora=ahora,
        horizonte=horizonte,
        ops=ops,
        recursos=recursos,
        operarios=operarios,
        turnos=turnos,
        festivos=festivos,
        aparatos=aparatos,
        tandas=tandas,
        of_numeros={o.id: o.numero for o in ofs},
        of_ops=dict(of_ops),
        of_sucesoras=dict(of_suc),
        of_predecesoras=dict(of_pred),
        fijas=fijas,
        config=cfg,
        ops_terminadas_por_aparato=dict(terminadas_por_aparato),
        ops_totales_por_aparato=dict(totales_por_aparato),
        extras=extras,
    )
