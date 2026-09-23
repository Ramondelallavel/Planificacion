"""Carga de trabajo: editar operaciones y OF a mano, repartir carga entre máquinas y
secciones, y medir la carga de cada equipo frente a su capacidad.

Todo cambio queda auditado y marcado con fuente USUARIO: las recargas de tiempos estándar
no pisan lo que ha fijado una persona. El plan cambia al replanificar.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from .. import configuracion
from ..modelos import Aparato, AsignacionPlan, Fichaje, OFAparato, Operacion, OrdenFabricacion, Recurso, Seccion, Tanda
from ..modelos.enums import ESTADOS_OF_CERRADOS, EstadoOF, EstadoOperacion, Fuente
from .auditoria import auditar
from .tandas import borrar_ofs

INICIADAS = {EstadoOperacion.EN_CURSO, EstadoOperacion.PAUSADA, EstadoOperacion.TERMINADA}
TANDA_VARIOS = "VARIOS"


def _horas_of(of: OrdenFabricacion) -> None:
    d = [o.duracion_estimada_min for o in of.operaciones]
    of.horas_estimadas = round(sum(d) / 60, 2) if d and all(x is not None for x in d) else None


def _renumerar(of: OrdenFabricacion) -> None:
    for i, o in enumerate(sorted(of.operaciones, key=lambda o: (o.secuencia, o.id or 0)), start=1):
        o.secuencia = i * 10


def _seccion_valida(s: Session, codigo: str | None) -> str | None:
    if not codigo:
        return None
    codigo = codigo.strip().upper()
    if s.get(Seccion, codigo) is None and not s.scalar(select(Recurso.id).where(Recurso.seccion_codigo == codigo).limit(1)):
        raise ValueError(f"No existe la sección {codigo}")
    return codigo


def _recurso(s: Session, codigo: str | None) -> Recurso | None:
    if not codigo:
        return None
    r = s.scalar(select(Recurso).where(func.upper(Recurso.codigo) == codigo.strip().upper()))
    if r is None:
        raise ValueError(f"No existe la máquina {codigo}")
    return r


def _foto(op: Operacion) -> dict:
    return {"tipo": op.tipo, "seccion": op.seccion_codigo, "minutos": op.duracion_estimada_min, "maquina": op.recurso_preferido, "descripcion": op.descripcion}


# ------------------------------------------------------------------ operaciones
def editar_operacion(s: Session, op_id: int, cambios: dict, usuario: str, motivo: str | None = None) -> dict:
    op = s.get(Operacion, op_id)
    if op is None:
        raise LookupError("Operación inexistente")
    if op.estado == EstadoOperacion.TERMINADA:
        raise ValueError("La operación ya está terminada")
    antes = _foto(op)
    if "minutos" in cambios and cambios["minutos"] is not None:
        m = float(cambios["minutos"])
        if m <= 0:
            raise ValueError("La duración tiene que ser mayor que cero")
        op.duracion_estimada_min = m
        op.origen_duracion = f"MANUAL: {usuario}" + (f" · {motivo}" if motivo else "")
    if "seccion" in cambios:
        op.seccion_codigo = _seccion_valida(s, cambios["seccion"]) or op.seccion_codigo
    if "maquina" in cambios:
        r = _recurso(s, cambios["maquina"])
        if r is not None:
            if r.seccion_codigo != op.seccion_codigo:
                op.seccion_codigo = r.seccion_codigo
            if r.operaciones and op.tipo not in r.operaciones:
                raise ValueError(f"La máquina {r.codigo} no hace operaciones de tipo {op.tipo} (hace: {', '.join(r.operaciones)})")
        op.recurso_preferido = r.codigo if r else None
    if cambios.get("descripcion") is not None:
        op.descripcion = cambios["descripcion"] or None
    if cambios.get("tipo"):
        op.tipo = str(cambios["tipo"]).strip().upper()
    op.fuente = Fuente.USUARIO
    _horas_of(op.of)
    auditar(s, usuario, "CAMBIO_OPERACION", "OF", op.of.numero, antes=antes, despues=_foto(op), motivo=motivo)
    return {"id": op.id, **_foto(op)}


def anadir_operacion(s: Session, of_id: int, datos: dict, usuario: str, motivo: str | None = None) -> dict:
    of = s.get(OrdenFabricacion, of_id)
    if of is None:
        raise LookupError("OF inexistente")
    if of.estado in ESTADOS_OF_CERRADOS:
        raise ValueError("La OF ya está terminada")
    tipo = str(datos.get("tipo") or "").strip().upper()
    if not tipo:
        raise ValueError("Indica el tipo de operación")
    minutos = float(datos.get("minutos") or 0)
    if minutos <= 0:
        raise ValueError("La duración tiene que ser mayor que cero")
    r = _recurso(s, datos.get("maquina"))
    seccion = (r.seccion_codigo if r else None) or _seccion_valida(s, datos.get("seccion")) or of.seccion_codigo
    _renumerar(of)  # de 10 en 10, para poder intercalar
    ops = sorted(of.operaciones, key=lambda o: o.secuencia)
    despues = datos.get("despues_de")
    if despues is not None and int(despues) == 0:
        secuencia = 5  # al principio
    elif despues:
        previa = next((o for o in ops if o.id == int(despues)), None)
        if previa is None:
            raise ValueError("La operación de referencia no es de esta OF")
        secuencia = previa.secuencia + 5
    else:
        secuencia = (ops[-1].secuencia + 10) if ops else 10
    op = Operacion(
        of_id=of.id, secuencia=secuencia, tipo=tipo, descripcion=datos.get("descripcion") or None, seccion_codigo=seccion, recurso_preferido=r.codigo if r else None,
        duracion_estimada_min=minutos, origen_duracion=f"MANUAL: {usuario}" + (f" · {motivo}" if motivo else ""), estado=EstadoOperacion.PENDIENTE, fuente=Fuente.USUARIO,
        cantidad=datos.get("cantidad"),
    )
    of.operaciones.append(op)
    s.flush()
    _renumerar(of)
    _horas_of(of)
    auditar(s, usuario, "ANADIR_OPERACION", "OF", of.numero, despues=_foto(op), motivo=motivo)
    return {"id": op.id, "secuencia": op.secuencia, **_foto(op)}


def eliminar_operacion(s: Session, op_id: int, usuario: str, motivo: str | None = None) -> dict:
    op = s.get(Operacion, op_id)
    if op is None:
        raise LookupError("Operación inexistente")
    if op.estado in INICIADAS or s.scalar(select(Fichaje.id).where(Fichaje.operacion_id == op.id).limit(1)):
        raise ValueError("La operación ya se ha empezado en planta: no se puede quitar")
    of = op.of
    if len(of.operaciones) <= 1:
        raise ValueError("Es la única operación de la OF: elimina la OF entera")
    antes = _foto(op)
    s.execute(delete(AsignacionPlan).where(AsignacionPlan.operacion_id == op.id))
    for o in of.operaciones:
        if o.operacion_anterior_id == op.id:
            o.operacion_anterior_id = op.operacion_anterior_id
    of.operaciones.remove(op)
    s.delete(op)
    s.flush()
    _renumerar(of)
    _horas_of(of)
    auditar(s, usuario, "QUITAR_OPERACION", "OF", of.numero, antes=antes, motivo=motivo)
    return {"of": of.numero, "operaciones": len(of.operaciones)}


# ------------------------------------------------------------------ OF a mano
def _tanda_varios(s: Session, semana: str | None) -> Tanda:
    t = s.scalar(select(Tanda).where(Tanda.numero == TANDA_VARIOS))
    if t is None:
        t = Tanda(numero=TANDA_VARIOS, producto="Trabajos añadidos a mano", semana_codigo=semana, estado="ACTIVA", incluida_en_plan=True)
        s.add(t)
        s.flush()
    elif t.estado != "ACTIVA":
        t.estado, t.incluida_en_plan = "ACTIVA", True
    return t


def crear_of(s: Session, datos: dict, usuario: str) -> dict:
    """OF que no viene de un PDF: retrabajos, reparaciones, pedidos sueltos…"""
    ops = datos.get("operaciones") or []
    if not ops:
        raise ValueError("Una OF necesita al menos una operación")
    semana = (datos.get("semana") or "").strip() or None
    if semana and not (len(semana) == 6 and semana.isdigit()):
        raise ValueError("La semana va en formato AAAASS, por ejemplo 202641")
    aparato = s.get(Aparato, int(datos["aparato_id"])) if datos.get("aparato_id") else None
    if datos.get("aparato_id") and aparato is None:
        raise ValueError("Aparato inexistente")
    if aparato is not None:
        tanda = aparato.tanda
    elif datos.get("tanda_id"):
        tanda = s.get(Tanda, int(datos["tanda_id"]))
        if tanda is None:
            raise ValueError("Tanda inexistente")
    else:
        tanda = _tanda_varios(s, semana)
    numero = (datos.get("numero") or "").strip()
    if not numero:
        n = s.scalar(select(func.count(OrdenFabricacion.id)).where(OrdenFabricacion.numero.like("M%"))) or 0
        while True:
            n += 1
            numero = f"M{n:05d}"
            if not s.scalar(select(OrdenFabricacion.id).where(OrdenFabricacion.numero == numero)):
                break
    elif s.scalar(select(OrdenFabricacion.id).where(OrdenFabricacion.numero == numero)):
        raise ValueError(f"Ya existe la OF {numero}")
    primera = ops[0]
    r0 = _recurso(s, primera.get("maquina"))
    seccion = (r0.seccion_codigo if r0 else None) or _seccion_valida(s, primera.get("seccion"))
    if not seccion:
        raise ValueError("Indica la sección o la máquina de la primera operación")
    of = OrdenFabricacion(
        numero=numero, tanda_id=tanda.id, aparato_id=aparato.id if aparato else None, seccion_codigo=seccion, descripcion=datos.get("descripcion") or None,
        semana_codigo=semana or (aparato.semana_codigo if aparato else tanda.semana_codigo), estado=EstadoOF.NO_INICIADA, urgente=bool(datos.get("urgente")),
        fuente=Fuente.USUARIO, tiene_hoja=True, cantidad_total=datos.get("cantidad"),
    )
    s.add(of)
    s.flush()
    if aparato is not None:
        s.add(OFAparato(of_id=of.id, aparato_id=aparato.id, lineas=0))
    for o in ops:
        anadir_operacion(s, of.id, o, usuario, "OF creada a mano")
    s.refresh(of)
    _horas_of(of)
    auditar(s, usuario, "CREAR_OF", "OF", of.numero, despues={"tanda": tanda.numero, "aparato": aparato.referencia if aparato else None, "operaciones": len(ops), "horas": of.horas_estimadas}, motivo=datos.get("motivo"))
    return {"id": of.id, "numero": of.numero, "tanda": tanda.numero, "horas": of.horas_estimadas}


def eliminar_of(s: Session, of_id: int, usuario: str, motivo: str | None = None) -> dict:
    of = s.get(OrdenFabricacion, of_id)
    if of is None:
        raise LookupError("OF inexistente")
    if s.scalar(select(Fichaje.id).where(Fichaje.of_id == of.id).limit(1)):
        raise ValueError(f"La OF {of.numero} tiene trabajo fichado en planta: no se puede eliminar")
    numero, horas = of.numero, of.horas_estimadas
    borrar_ofs(s, [of.id])
    s.expire(of)
    s.delete(s.get(OrdenFabricacion, of_id))
    s.flush()
    auditar(s, usuario, "ELIMINAR_OF", "OF", numero, antes={"horas": horas}, motivo=motivo)
    return {"numero": numero}


# ------------------------------------------------------------------ repartir carga
def mover_carga(s: Session, datos: dict, usuario: str, aplicar: bool = True) -> dict:
    """Pasa operaciones pendientes de una máquina o sección a otra.

    datos: desde_maquina | desde_seccion, hacia_maquina | hacia_seccion, tipo?, tanda_id?,
    fijar_maquina (por defecto sí cuando hay máquina destino). Con aplicar=False solo cuenta.
    """
    desde_r = _recurso(s, datos.get("desde_maquina"))
    desde_sec = _seccion_valida(s, datos.get("desde_seccion")) if not desde_r else desde_r.seccion_codigo
    hacia_r = _recurso(s, datos.get("hacia_maquina"))
    hacia_sec = (hacia_r.seccion_codigo if hacia_r else None) or _seccion_valida(s, datos.get("hacia_seccion"))
    if not desde_sec or not hacia_sec:
        raise ValueError("Indica de dónde y a dónde se mueve la carga")
    if desde_r and hacia_r and desde_r.id == hacia_r.id:
        raise ValueError("La máquina de origen y la de destino son la misma")
    tipo = (datos.get("tipo") or "").strip().upper() or None
    fijar = bool(datos.get("fijar_maquina", hacia_r is not None)) and hacia_r is not None
    q = (
        select(Operacion, OrdenFabricacion)
        .join(OrdenFabricacion, OrdenFabricacion.id == Operacion.of_id)
        .join(Tanda, Tanda.id == OrdenFabricacion.tanda_id)
        .where(Operacion.seccion_codigo == desde_sec, Operacion.estado.not_in(list(INICIADAS)), OrdenFabricacion.estado.not_in(list(ESTADOS_OF_CERRADOS)), Tanda.estado == "ACTIVA")
    )
    if tipo:
        q = q.where(Operacion.tipo == tipo)
    if datos.get("tanda_id"):
        q = q.where(OrdenFabricacion.tanda_id == int(datos["tanda_id"]))
    if datos.get("of_ids"):
        q = q.where(OrdenFabricacion.id.in_([int(x) for x in datos["of_ids"]]))
    candidatas = list(s.execute(q))
    if desde_r is not None:
        # de una máquina concreta: lo fijado a ella, o lo que el plan activo le ha asignado
        from ..planificacion.servicio import plan_activo

        plan = plan_activo(s)
        en_plan = set(s.scalars(select(AsignacionPlan.operacion_id).where(AsignacionPlan.plan_id == plan.id, AsignacionPlan.recurso_id == desde_r.id))) if plan else set()
        candidatas = [(op, of) for op, of in candidatas if op.recurso_preferido == desde_r.codigo or (not op.recurso_preferido and op.id in en_plan)]
    movidas, rechazadas, minutos = [], [], 0.0
    for op, of in candidatas:
        if hacia_r is not None and hacia_r.operaciones and op.tipo not in hacia_r.operaciones:
            rechazadas.append(f"OF {of.numero} {op.tipo}")
            continue
        movidas.append((op, of))
        minutos += op.duracion_estimada_min or 0
    if aplicar and movidas:
        for op, _of in movidas:
            op.seccion_codigo = hacia_sec
            op.recurso_preferido = hacia_r.codigo if fijar else None
            op.fuente = Fuente.USUARIO
        auditar(
            s, usuario, "MOVER_CARGA", "SECCION", desde_sec,
            antes={"maquina": desde_r.codigo if desde_r else None, "seccion": desde_sec},
            despues={"maquina": hacia_r.codigo if hacia_r else None, "seccion": hacia_sec, "tipo": tipo, "operaciones": len(movidas), "horas": round(minutos / 60, 1)},
            motivo=datos.get("motivo"),
        )
    return {
        "operaciones": len(movidas), "horas": round(minutos / 60, 1), "ofs": len({of.id for _op, of in movidas}), "rechazadas": rechazadas[:20], "n_rechazadas": len(rechazadas),
        "desde": desde_r.codigo if desde_r else desde_sec, "hacia": hacia_r.codigo if hacia_r else hacia_sec, "aplicado": aplicar and bool(movidas),
    }


# ------------------------------------------------------------------ carga por equipo
def resumen_carga(s: Session, ahora: datetime, dias: int = 14) -> dict:
    """Demanda pendiente (horas de operaciones sin terminar de las tandas del plan) frente a la
    capacidad de máquinas y personas de cada sección en los próximos días."""
    from ..planificacion.modelo import cargar_instantanea

    inst = cargar_instantanea(s, ahora)
    hasta = min(ahora + timedelta(days=max(1, min(dias, 42))), inst.horizonte)
    rend = {k: float(v) for k, v in configuracion.obtener(s, "rendimiento_secciones").items()}
    tandas = {t.id: t.numero for t in s.scalars(select(Tanda))}
    sec: dict[str, dict] = defaultdict(lambda: {"demanda_min": 0.0, "demanda_base_min": 0.0, "operaciones": 0, "sin_tiempo": 0, "maq_min": 0.0, "per_min": 0.0, "maquinas": [], "operarios": [], "por_tanda": defaultdict(float), "por_tipo": defaultdict(float)})
    por_maquina: dict[str, float] = defaultdict(float)
    for op in inst.ops.values():
        d = sec[op.seccion or "—"]
        minutos = max(0.0, (op.duracion or 0) - op.minutos_hechos)
        d["demanda_min"] += minutos
        d["demanda_base_min"] += minutos * rend.get(op.seccion or "", 100.0) / 100
        d["operaciones"] += 1
        d["sin_tiempo"] += op.duracion is None
        d["por_tanda"][tandas.get(op.tanda_id, "—")] += minutos
        d["por_tipo"][op.tipo] += minutos
        if op.recurso_preferido:
            por_maquina[op.recurso_preferido] += minutos
    for r in inst.recursos.values():
        d = sec[r.seccion or "—"]
        disp = inst.ventanas_recurso(r).minutos(ahora, hasta) * max(1, r.capacidad)
        d["maq_min"] += disp
        d["maquinas"].append({"id": r.id, "codigo": r.codigo, "nombre": r.nombre, "unidades": r.capacidad, "estado": r.estado, "horas_disponibles": round(disp / 60, 1), "horas_fijadas": round(por_maquina.get(r.codigo, 0) / 60, 1), "operaciones": r.operaciones or []})
    codigos_sec = {r.codigo: r.seccion for r in inst.recursos.values()}
    for o in inst.operarios.values():
        secciones = {codigos_sec[c] for c in o.recursos if c in codigos_sec}
        disp = inst.ventanas_operario(o).minutos(ahora, hasta)
        for x in secciones:
            sec[x or "—"]["per_min"] += disp / len(secciones)  # quien sabe de varias secciones reparte su tiempo
            sec[x or "—"]["operarios"].append({"id": o.id, "codigo": o.codigo, "nombre": o.nombre, "turno": o.turno, "compartido": len(secciones) > 1})
    nombres = {x.codigo: x.nombre for x in s.scalars(select(Seccion))}
    salida = []
    for codigo, d in sorted(sec.items()):
        maq, per = d["maq_min"], d["per_min"]
        necesita_personas = any(r.requiere_operario for r in inst.recursos.values() if (r.seccion or "—") == codigo)
        capacidad = min(maq, per) if necesita_personas and per > 0 else maq
        salida.append({
            "seccion": codigo, "nombre": nombres.get(codigo), "rendimiento": rend.get(codigo, 100.0),
            "demanda_h": round(d["demanda_min"] / 60, 1), "demanda_base_h": round(d["demanda_base_min"] / 60, 1), "operaciones": d["operaciones"], "sin_tiempo": d["sin_tiempo"],
            "capacidad_maquinas_h": round(maq / 60, 1), "capacidad_personas_h": round(per / 60, 1), "capacidad_h": round(capacidad / 60, 1),
            "carga": round(d["demanda_min"] / capacidad, 3) if capacidad else None,
            "limitada_por": ("personas" if necesita_personas and 0 < per < maq else "maquinas") if capacidad else "sin capacidad",
            "maquinas": d["maquinas"], "operarios": d["operarios"],
            "por_tanda": sorted(({"tanda": k, "horas": round(v / 60, 1)} for k, v in d["por_tanda"].items()), key=lambda x: -x["horas"]),
            "por_tipo": sorted(({"tipo": k, "horas": round(v / 60, 1)} for k, v in d["por_tipo"].items()), key=lambda x: -x["horas"]),
        })
    return {"ahora": ahora.isoformat(), "hasta": hasta.isoformat(), "dias": (hasta - ahora).days, "secciones": salida}
