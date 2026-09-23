"""Materiales: necesidades de las OF abiertas frente a stock y entradas previstas.

Necesidad de una OF = sus «Consumidos» (barras, tubos, perfiles…) más sus componentes de compra
(líneas ENTRADA_COMPRA y CONSUMO_MATERIAL), tal y como vienen en el PDF.

Para cada material controlado se reparte el stock y después las entradas previstas, por orden
de necesidad (inicio en el plan activo; sin plan, urgentes y semana más próxima primero). Cada OF
queda:
  * con material, si el stock la cubre;
  * con material a partir de la fecha de la entrada que la cubre (el motor no la empieza antes);
  * bloqueada por material, si ni stock ni entradas la cubren (salvo plazo de reposición
    configurado en el material: entonces se supone disponible pasado ese plazo).
Los materiales no controlados no cambian nada: su disponibilidad la sigue diciendo el MRP o una
persona en la propia OF.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from ..modelos import AsignacionPlan, LineaOF, Material, OrdenFabricacion, Origen, Tanda
from ..modelos.enums import ESTADOS_OF_CERRADOS, Fuente, TipoLineaOF
from .auditoria import auditar

MARCA = "Cálculo de materiales"
LEJOS = datetime(9999, 1, 1)


@dataclass
class Necesidad:
    of_id: int
    of: str
    cantidad: float
    inicio: datetime | None
    urgente: bool
    semana: str | None
    descripcion: str | None = None


@dataclass
class Evaluacion:
    codigo: str
    necesidad: float = 0.0
    stock: float = 0.0
    entradas: float = 0.0
    ofs: list[dict] = field(default_factory=list)  # [{of, of_id, cantidad, estado, fecha}]


def necesidades(s: Session) -> tuple[dict[str, list[Necesidad]], dict[str, str]]:
    """Necesidades por artículo de las OF abiertas de tandas activas, y descripciones."""
    from ..planificacion.servicio import plan_activo

    ofs = {
        o.id: o
        for o in s.scalars(
            select(OrdenFabricacion).join(Tanda, Tanda.id == OrdenFabricacion.tanda_id).where(Tanda.estado == "ACTIVA", OrdenFabricacion.estado.not_in(list(ESTADOS_OF_CERRADOS)))
        )
    }
    plan = plan_activo(s)
    inicios: dict[int, datetime] = {}
    if plan is not None:
        inicios = dict(s.execute(select(AsignacionPlan.of_id, func.min(AsignacionPlan.inicio)).where(AsignacionPlan.plan_id == plan.id).group_by(AsignacionPlan.of_id)).all())
    salida: dict[str, list[Necesidad]] = defaultdict(list)
    desc: dict[str, str] = {}

    def anadir(codigo: str | None, cantidad: float | None, of: OrdenFabricacion, d: str | None) -> None:
        if not codigo or not cantidad or cantidad <= 0:
            return
        if d and codigo not in desc:
            desc[codigo] = d
        lista = salida[codigo]
        previa = next((n for n in lista if n.of_id == of.id), None)
        if previa:
            previa.cantidad += cantidad
        else:
            lista.append(Necesidad(of.id, of.numero, cantidad, inicios.get(of.id) or of.fecha_prevista_inicio, bool(of.urgente), of.semana_codigo, d))

    for of in ofs.values():
        for c in of.consumos or []:
            anadir(c.get("articulo"), c.get("total"), of, c.get("descripcion"))
    for i in range(0, len(ofs), 500):
        ids = list(ofs)[i : i + 500]
        for ln in s.scalars(select(LineaOF).where(LineaOF.of_id.in_(ids), LineaOF.tipo.in_([TipoLineaOF.ENTRADA_COMPRA, TipoLineaOF.CONSUMO_MATERIAL]))):
            anadir(ln.articulo_codigo, ln.cantidad, ofs[ln.of_id], ln.articulo_descripcion)
    return salida, desc


def _orden(n: Necesidad) -> tuple:
    return (n.inicio or LEJOS, not n.urgente, n.semana or "999999", n.of)


def evaluar(s: Session, ahora: datetime) -> tuple[dict[str, Evaluacion], dict[int, dict]]:
    """Reparto de stock y entradas. Devuelve la evaluación por material y el resultado por OF:
    {of_id: {"fecha": datetime|None, "bloqueada": bool, "faltas": [texto]}}."""
    nec, _ = necesidades(s)
    por_of: dict[int, dict] = {}
    evaluacion: dict[str, Evaluacion] = {}
    for m in s.scalars(select(Material).where(Material.controlado.is_(True))):
        pendientes = sorted((e for e in m.entradas if not e.recibida), key=lambda e: e.fecha_prevista)
        ev = Evaluacion(m.codigo, stock=m.stock or 0.0, entradas=sum(e.cantidad for e in pendientes))
        acumulado = 0.0
        for n in sorted(nec.get(m.codigo, []), key=_orden):
            acumulado += n.cantidad
            ev.necesidad += n.cantidad
            r = por_of.setdefault(n.of_id, {"fecha": None, "bloqueada": False, "faltas": []})
            fecha, estado = None, "CUBIERTA"
            if acumulado > ev.stock + 1e-9:
                suministro = ev.stock
                for e in pendientes:
                    suministro += e.cantidad
                    if suministro + 1e-9 >= acumulado:
                        fecha, estado = max(e.fecha_prevista, ahora), "CON_ENTRADA"
                        break
                else:
                    if m.plazo_dias:
                        fecha, estado = ahora + timedelta(days=m.plazo_dias), "REPOSICION"
                    else:
                        estado = "FALTA"
            if estado == "FALTA":
                r["bloqueada"] = True
                r["faltas"].append(f"falta {m.codigo} ({m.descripcion or ''})".strip())
            elif fecha is not None:
                r["fecha"] = max(filter(None, [r["fecha"], fecha]))
                r["faltas"].append(f"{m.codigo} llega el {fecha:%d/%m}")
            ev.ofs.append({"of": n.of, "of_id": n.of_id, "cantidad": round(n.cantidad, 3), "estado": estado, "fecha": fecha.isoformat() if fecha else None, "inicio_plan": n.inicio.isoformat() if n.inicio else None})
        evaluacion[m.codigo] = ev
    return evaluacion, por_of


def calcular(s: Session, usuario: str, ahora: datetime) -> dict:
    """Aplica la disponibilidad de material a las OF (lo que el motor usa al planificar)."""
    evaluacion, por_of = evaluar(s, ahora)
    previas = set(s.scalars(select(Origen.entidad_id).where(Origen.entidad_tipo == "OF", Origen.campo == "material_disponible", Origen.detalle.like(f"{MARCA}%"))))
    s.execute(delete(Origen).where(Origen.entidad_tipo == "OF", Origen.campo == "material_disponible", Origen.detalle.like(f"{MARCA}%")))
    cont = {"con_material": 0, "con_fecha": 0, "bloqueadas": 0, "liberadas": 0}
    for of_id, r in por_of.items():
        of = s.get(OrdenFabricacion, of_id)
        if of is None:
            continue
        if r["bloqueada"]:
            of.material_disponible, of.material_disponible_desde = False, None
            cont["bloqueadas"] += 1
        elif r["fecha"] is not None:
            of.material_disponible, of.material_disponible_desde = False, r["fecha"]
            cont["con_fecha"] += 1
        else:
            of.material_disponible, of.material_disponible_desde = True, None
            cont["con_material"] += 1
        s.add(Origen(entidad_tipo="OF", entidad_id=of_id, campo="material_disponible", fuente=Fuente.USUARIO, detalle=f"{MARCA}: {'; '.join(r['faltas']) or 'cubierta por stock'}"[:240]))
    # OF que ya no dependen de ningún material controlado: vuelven a «sin dato»
    for of_id in previas - set(por_of):
        of = s.get(OrdenFabricacion, of_id)
        if of is not None and of.estado not in ESTADOS_OF_CERRADOS:
            of.material_disponible, of.material_disponible_desde = None, None
            cont["liberadas"] += 1
    auditar(s, usuario, "CALCULAR_MATERIALES", "MATERIAL", None, despues={**cont, "materiales": len(evaluacion)})
    return {**cont, "materiales": len(evaluacion)}


def listado(s: Session, ahora: datetime) -> dict:
    nec, desc = necesidades(s)
    evaluacion, por_of = evaluar(s, ahora)
    materiales = {m.codigo: m for m in s.scalars(select(Material))}
    filas = []
    for codigo in sorted(set(nec) | set(materiales)):
        m = materiales.get(codigo)
        ev = evaluacion.get(codigo)
        necesidad = sum(n.cantidad for n in nec.get(codigo, []))
        pendientes = [e for e in (m.entradas if m else []) if not e.recibida]
        filas.append({
            "codigo": codigo, "descripcion": (m.descripcion if m and m.descripcion else None) or desc.get(codigo), "unidad": m.unidad if m else None,
            "controlado": bool(m and m.controlado), "registrado": m is not None, "stock": m.stock if m else None, "plazo_dias": m.plazo_dias if m else None,
            "necesidad": round(necesidad, 3), "ofs": len(nec.get(codigo, [])),
            "entradas": [{"id": e.id, "cantidad": e.cantidad, "fecha": e.fecha_prevista.isoformat(), "referencia": e.referencia} for e in pendientes],
            "balance": round((m.stock or 0) + sum(e.cantidad for e in pendientes) - necesidad, 3) if m else None,
            "ofs_falta": sum(1 for o in (ev.ofs if ev else []) if o["estado"] == "FALTA"),
            "ofs_esperan": sum(1 for o in (ev.ofs if ev else []) if o["estado"] in ("CON_ENTRADA", "REPOSICION")),
            "notas": m.notas if m else None,
        })
    return {
        "materiales": filas,
        "resumen": {
            "controlados": sum(1 for f in filas if f["controlado"]), "necesarios": len(nec), "con_falta": sum(1 for f in filas if f["ofs_falta"]),
            "ofs_bloqueadas": sum(1 for r in por_of.values() if r["bloqueada"]), "ofs_esperan": sum(1 for r in por_of.values() if not r["bloqueada"] and r["fecha"]),
        },
    }


def detalle(s: Session, codigo: str, ahora: datetime) -> dict:
    nec, desc = necesidades(s)
    evaluacion, _ = evaluar(s, ahora)
    ev = evaluacion.get(codigo)
    if ev is not None:
        consumidores = ev.ofs
    else:
        consumidores = [{"of": n.of, "of_id": n.of_id, "cantidad": round(n.cantidad, 3), "estado": "SIN_CONTROL", "fecha": None, "inicio_plan": n.inicio.isoformat() if n.inicio else None} for n in sorted(nec.get(codigo, []), key=_orden)]
    return {"codigo": codigo, "descripcion": desc.get(codigo), "consumidores": consumidores}
