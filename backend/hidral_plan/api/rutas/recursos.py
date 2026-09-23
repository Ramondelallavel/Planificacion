"""Configuración de fábrica: secciones, recursos (máquinas/puestos), operarios, turnos,
tiempos estándar y parámetros de negocio. Todo cambio queda auditado."""

from __future__ import annotations

from datetime import date, datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from ... import configuracion
from ...modelos import Ausencia, Cualificacion, Festivo, JornadaExtra, Operacion, Operario, OrdenFabricacion, ParadaRecurso, Recurso, Seccion, TiempoEstandar, Turno
from ...modelos.enums import EstadoOperacion, Fuente
from ...servicios.auditoria import auditar
from ...servicios.operaciones import derivar_operaciones
from ..deps import UsuarioActual, ahora, get_sesion, requiere

router = APIRouter(tags=["configuración de fábrica"])


def _rec(r: Recurso, s: Session) -> dict:
    ahora_ = ahora()
    parada = s.scalar(select(ParadaRecurso).where(ParadaRecurso.recurso_id == r.id, ParadaRecurso.inicio <= ahora_, (ParadaRecurso.fin.is_(None)) | (ParadaRecurso.fin > ahora_)))
    return {
        "id": r.id, "codigo": r.codigo, "nombre": r.nombre, "tipo": r.tipo, "seccion": r.seccion_codigo, "capacidad": r.capacidad, "estado": r.estado,
        "operaciones": r.operaciones, "alias": r.alias, "grupos_hf": r.grupos_hf, "turnos": r.turnos, "requiere_operario": r.requiere_operario,
        "restricciones": r.restricciones, "activo": r.activo, "fuente": r.fuente,
        "parada_actual": {"inicio": parada.inicio.isoformat(), "fin": parada.fin.isoformat() if parada.fin else None, "motivo": parada.motivo} if parada else None,
    }


@router.get("/secciones")
def secciones(s: Session = Depends(get_sesion), _: UsuarioActual = Depends(requiere("ver"))) -> list[dict]:
    return [
        {"codigo": x.codigo, "codigo_completo": x.codigo_completo, "nombre": x.nombre, "flujo": x.flujo, "requiere_programacion": x.requiere_programacion, "conocida": x.conocida, "fuente": x.fuente}
        for x in s.scalars(select(Seccion).order_by(Seccion.codigo))
    ]


class SeccionIn(BaseModel):
    nombre: str | None = None
    flujo: str | None = None
    requiere_programacion: bool | None = None


@router.patch("/secciones/{codigo}")
def cambiar_seccion(codigo: str, datos: SeccionIn, s: Session = Depends(get_sesion), u: UsuarioActual = Depends(requiere("recursos"))) -> dict:
    x = s.get(Seccion, codigo)
    if x is None:
        raise HTTPException(404, "Sección inexistente")
    antes = {"nombre": x.nombre, "flujo": x.flujo, "requiere_programacion": x.requiere_programacion}
    for k, v in datos.model_dump(exclude_unset=True).items():
        setattr(x, k, v)
    x.conocida, x.fuente = True, Fuente.USUARIO
    auditar(s, u.usuario, "CAMBIO_SECCION", "SECCION", codigo, antes=antes, despues=datos.model_dump(exclude_unset=True))
    return {"codigo": codigo}


@router.get("/recursos")
def recursos(s: Session = Depends(get_sesion), _: UsuarioActual = Depends(requiere("ver"))) -> list[dict]:
    return [_rec(r, s) for r in s.scalars(select(Recurso).order_by(Recurso.seccion_codigo, Recurso.codigo))]


class RecursoIn(BaseModel):
    codigo: str | None = None
    nombre: str | None = None
    tipo: str | None = None
    seccion: str | None = None
    capacidad: int | None = None
    operaciones: list[str] | None = None
    alias: list[str] | None = None
    turnos: list[str] | None = None
    requiere_operario: bool | None = None
    restricciones: dict | None = None
    activo: bool | None = None
    estado: str | None = None


@router.post("/recursos")
def crear_recurso(datos: RecursoIn, s: Session = Depends(get_sesion), u: UsuarioActual = Depends(requiere("recursos"))) -> dict:
    if not datos.codigo or not datos.nombre or not datos.seccion:
        raise HTTPException(400, "codigo, nombre y seccion son obligatorios")
    if s.scalar(select(Recurso).where(Recurso.codigo == datos.codigo)):
        raise HTTPException(409, "Ya existe un recurso con ese código")
    r = Recurso(
        codigo=datos.codigo, nombre=datos.nombre, tipo=datos.tipo or "PUESTO", seccion_codigo=datos.seccion, capacidad=datos.capacidad or 1,
        operaciones=datos.operaciones, alias=datos.alias, turnos=datos.turnos, requiere_operario=datos.requiere_operario if datos.requiere_operario is not None else True,
        restricciones=datos.restricciones, fuente=Fuente.USUARIO,
    )
    s.add(r)
    s.flush()
    auditar(s, u.usuario, "CREAR_RECURSO", "RECURSO", r.codigo, despues=datos.model_dump())
    return _rec(r, s)


@router.patch("/recursos/{rid}")
def cambiar_recurso(rid: int, datos: RecursoIn, s: Session = Depends(get_sesion), u: UsuarioActual = Depends(requiere("recursos"))) -> dict:
    r = s.get(Recurso, rid)
    if r is None:
        raise HTTPException(404, "Recurso inexistente")
    antes = _rec(r, s)
    campos = datos.model_dump(exclude_unset=True)
    if "seccion" in campos:
        r.seccion_codigo = campos.pop("seccion")
    for k, v in campos.items():
        setattr(r, k, v)
    auditar(s, u.usuario, "CAMBIO_RECURSO", "RECURSO", r.codigo, antes=antes, despues=datos.model_dump(exclude_unset=True))
    return _rec(r, s)


@router.get("/operarios")
def operarios(s: Session = Depends(get_sesion), _: UsuarioActual = Depends(requiere("ver"))) -> list[dict]:
    ahora_ = ahora()
    ausentes = {a.operario_id: a for a in s.scalars(select(Ausencia).where(Ausencia.inicio <= ahora_, (Ausencia.fin.is_(None)) | (Ausencia.fin > ahora_)))}
    return [
        {
            "id": o.id, "codigo": o.codigo_empleado, "nombre": o.nombre, "turno": o.turno_codigo, "seccion": o.seccion_codigo, "activo": o.activo,
            "cualificaciones": [{"recurso": c.recurso_codigo, "operacion": c.tipo_operacion, "nivel": c.nivel} for c in o.cualificaciones],
            "ausente": {"motivo": ausentes[o.id].motivo, "fin": ausentes[o.id].fin.isoformat() if ausentes[o.id].fin else None} if o.id in ausentes else None,
        }
        for o in s.scalars(select(Operario).order_by(Operario.codigo_empleado))
    ]


class OperarioIn(BaseModel):
    codigo: str | None = None
    nombre: str | None = None
    turno: str | None = None
    seccion: str | None = None
    activo: bool | None = None
    recursos: list[str] | None = None
    operaciones: list[str] | None = None


@router.post("/operarios")
def crear_operario(datos: OperarioIn, s: Session = Depends(get_sesion), u: UsuarioActual = Depends(requiere("recursos"))) -> dict:
    if not datos.codigo or not datos.nombre:
        raise HTTPException(400, "codigo y nombre son obligatorios")
    o = Operario(codigo_empleado=datos.codigo, nombre=datos.nombre, turno_codigo=datos.turno, seccion_codigo=datos.seccion)
    o.cualificaciones = [Cualificacion(recurso_codigo=r) for r in datos.recursos or []] + [Cualificacion(tipo_operacion=t) for t in datos.operaciones or []]
    s.add(o)
    s.flush()
    auditar(s, u.usuario, "CREAR_OPERARIO", "OPERARIO", o.codigo_empleado, despues=datos.model_dump())
    return {"id": o.id}


@router.patch("/operarios/{oid}")
def cambiar_operario(oid: int, datos: OperarioIn, s: Session = Depends(get_sesion), u: UsuarioActual = Depends(requiere("recursos"))) -> dict:
    o = s.get(Operario, oid)
    if o is None:
        raise HTTPException(404, "Operario inexistente")
    antes = {"turno": o.turno_codigo, "activo": o.activo, "cualificaciones": [(c.recurso_codigo, c.tipo_operacion) for c in o.cualificaciones]}
    c = datos.model_dump(exclude_unset=True)
    if "nombre" in c:
        o.nombre = c["nombre"]
    if "turno" in c:
        o.turno_codigo = c["turno"]
    if "seccion" in c:
        o.seccion_codigo = c["seccion"]
    if "activo" in c:
        o.activo = c["activo"]
    if "recursos" in c or "operaciones" in c:
        o.cualificaciones = [Cualificacion(recurso_codigo=r) for r in (datos.recursos or [])] + [Cualificacion(tipo_operacion=t) for t in (datos.operaciones or [])]
    auditar(s, u.usuario, "CAMBIO_OPERARIO", "OPERARIO", o.codigo_empleado, antes=antes, despues=c)
    return {"id": o.id}


@router.get("/turnos")
def turnos(s: Session = Depends(get_sesion), _: UsuarioActual = Depends(requiere("ver"))) -> list[dict]:
    return [{"codigo": t.codigo, "nombre": t.nombre, "hora_inicio": t.hora_inicio, "hora_fin": t.hora_fin, "dias_semana": t.dias_semana, "pausas": t.pausas, "activo": t.activo} for t in s.scalars(select(Turno))]


class TurnoIn(BaseModel):
    codigo: str
    nombre: str
    hora_inicio: str
    hora_fin: str
    dias_semana: list[int] = [0, 1, 2, 3, 4]
    pausas: list[dict] | None = None
    activo: bool = True


@router.put("/turnos/{codigo}")
def guardar_turno(codigo: str, datos: TurnoIn, s: Session = Depends(get_sesion), u: UsuarioActual = Depends(requiere("recursos"))) -> dict:
    t = s.get(Turno, codigo) or Turno(codigo=codigo)
    antes = {"hora_inicio": t.hora_inicio, "hora_fin": t.hora_fin, "dias": t.dias_semana} if t.nombre else None
    t.nombre, t.hora_inicio, t.hora_fin, t.dias_semana, t.pausas, t.activo = datos.nombre, datos.hora_inicio, datos.hora_fin, datos.dias_semana, datos.pausas, datos.activo
    s.add(t)
    auditar(s, u.usuario, "GUARDAR_TURNO", "TURNO", codigo, antes=antes, despues=datos.model_dump())
    return {"codigo": codigo}


@router.get("/tiempos-estandar")
def tiempos(todos: bool = False, s: Session = Depends(get_sesion), _: UsuarioActual = Depends(requiere("ver"))) -> list[dict]:
    q = select(TiempoEstandar).order_by(TiempoEstandar.seccion_codigo, TiempoEstandar.tipo_operacion, TiempoEstandar.version.desc())
    if not todos:
        q = q.where(TiempoEstandar.vigente.is_(True))
    return [
        {
            "id": t.id, "seccion": t.seccion_codigo, "grupo_hf": t.grupo_hf, "articulo": t.articulo_codigo, "tipo_operacion": t.tipo_operacion,
            "minutos_preparacion": t.minutos_preparacion, "minutos_por_unidad": t.minutos_por_unidad, "minutos_por_linea": t.minutos_por_linea,
            "fuente": t.fuente, "es_ejemplo": t.es_ejemplo, "version": t.version, "vigente": t.vigente, "creado": t.creado.isoformat(), "creado_por": t.creado_por, "notas": t.notas,
        }
        for t in s.scalars(q)
    ]


class TiempoIn(BaseModel):
    seccion: str
    grupo_hf: str | None = None
    articulo: str | None = None
    tipo_operacion: str | None = None
    minutos_preparacion: float = 0
    minutos_por_unidad: float = 0
    minutos_por_linea: float = 0
    notas: str | None = None


@router.post("/tiempos-estandar")
def nuevo_tiempo(datos: TiempoIn, s: Session = Depends(get_sesion), u: UsuarioActual = Depends(requiere("configurar"))) -> dict:
    """Crea una NUEVA versión; la anterior del mismo ámbito queda como histórico (no se sobreescribe)."""
    previos = list(
        s.scalars(
            select(TiempoEstandar).where(
                TiempoEstandar.vigente.is_(True), TiempoEstandar.seccion_codigo == datos.seccion,
                (TiempoEstandar.grupo_hf == datos.grupo_hf) if datos.grupo_hf else TiempoEstandar.grupo_hf.is_(None),
                (TiempoEstandar.articulo_codigo == datos.articulo) if datos.articulo else TiempoEstandar.articulo_codigo.is_(None),
                (TiempoEstandar.tipo_operacion == datos.tipo_operacion) if datos.tipo_operacion else TiempoEstandar.tipo_operacion.is_(None),
            )
        )
    )
    for p in previos:
        p.vigente = False
    t = TiempoEstandar(
        seccion_codigo=datos.seccion, grupo_hf=datos.grupo_hf, articulo_codigo=datos.articulo, tipo_operacion=datos.tipo_operacion,
        minutos_preparacion=datos.minutos_preparacion, minutos_por_unidad=datos.minutos_por_unidad, minutos_por_linea=datos.minutos_por_linea,
        fuente=Fuente.USUARIO, es_ejemplo=False, version=max((p.version for p in previos), default=0) + 1, creado_por=u.usuario, notas=datos.notas,
    )
    s.add(t)
    s.flush()
    auditar(s, u.usuario, "NUEVO_TIEMPO_ESTANDAR", "TIEMPO_ESTANDAR", t.id, antes=[p.id for p in previos], despues=datos.model_dump())
    return {"id": t.id, "sustituye": [p.id for p in previos]}


@router.post("/tiempos-estandar/recalcular")
def recalcular(s: Session = Depends(get_sesion), u: UsuarioActual = Depends(requiere("configurar"))) -> dict:
    """Vuelve a derivar operaciones y duraciones de las OF no iniciadas con la configuración vigente."""
    of_ids = [i for (i,) in s.execute(select(OrdenFabricacion.id).where(OrdenFabricacion.estado.not_in(["TERMINADA", "VALIDADA"])))]
    r = derivar_operaciones(s, of_ids, None, u.usuario)
    auditar(s, u.usuario, "RECALCULAR_OPERACIONES", "OF", None, despues=r)
    sin = s.scalar(select(Operacion.id).where(Operacion.duracion_estimada_min.is_(None), Operacion.estado != EstadoOperacion.TERMINADA).limit(1))
    return {**r, "quedan_sin_tiempo": sin is not None}


@router.get("/configuracion")
def config(s: Session = Depends(get_sesion), _: UsuarioActual = Depends(requiere("ver"))) -> dict:
    return configuracion.todos(s)


class ParametroIn(BaseModel):
    valor: dict
    motivo: str | None = None


@router.put("/configuracion/{clave}")
def guardar_config(clave: str, datos: ParametroIn, s: Session = Depends(get_sesion), u: UsuarioActual = Depends(requiere("configurar"))) -> dict:
    try:
        f = configuracion.guardar(s, clave, datos.valor, u.usuario, datos.motivo)
    except KeyError as e:
        raise HTTPException(404, str(e)) from e
    return {"clave": clave, "version": f.version}


class AusenciaIn(BaseModel):
    inicio: datetime
    fin: datetime | None = None
    motivo: str


@router.post("/operarios/{oid}/ausencias")
def ausencia(oid: int, datos: AusenciaIn, s: Session = Depends(get_sesion), u: UsuarioActual = Depends(requiere("recursos"))) -> dict:
    """Ausencia planificada (vacaciones, formación). Para una ausencia imprevista con
    replanificación usar POST /incidencias con tipo AUSENCIA."""
    s.add(Ausencia(operario_id=oid, inicio=datos.inicio, fin=datos.fin, motivo=datos.motivo))
    auditar(s, u.usuario, "AUSENCIA_PLANIFICADA", "OPERARIO", oid, despues={"inicio": datos.inicio.isoformat(), "fin": datos.fin.isoformat() if datos.fin else None, "motivo": datos.motivo})
    return {"operario_id": oid}


# ------------------------------------------------------------------ calendario laboral
@router.get("/calendario")
def calendario(desde: date | None = None, s: Session = Depends(get_sesion), _: UsuarioActual = Depends(requiere("ver"))) -> dict:
    """Festivos y jornadas extra (turnos fuera del calendario habitual) a partir de `desde`."""
    desde = desde or ahora().date().replace(day=1)
    return {
        "festivos": [{"fecha": f.fecha.isoformat(), "descripcion": f.descripcion} for f in s.scalars(select(Festivo).where(Festivo.fecha >= desde).order_by(Festivo.fecha))],
        "jornadas_extra": [
            {"id": j.id, "fecha": j.fecha.isoformat(), "turno": j.turno_codigo, "secciones": j.secciones, "motivo": j.motivo, "creado_por": j.creado_por}
            for j in s.scalars(select(JornadaExtra).where(JornadaExtra.fecha >= desde).order_by(JornadaExtra.fecha))
        ],
    }


class FestivoIn(BaseModel):
    fecha: date
    descripcion: str | None = None


@router.post("/calendario/festivos")
def nuevo_festivo(datos: FestivoIn, s: Session = Depends(get_sesion), u: UsuarioActual = Depends(requiere("recursos"))) -> dict:
    f = s.get(Festivo, datos.fecha) or Festivo(fecha=datos.fecha)
    f.descripcion = datos.descripcion
    s.add(f)
    auditar(s, u.usuario, "FESTIVO", "CALENDARIO", datos.fecha.isoformat(), despues={"descripcion": datos.descripcion})
    return {"fecha": datos.fecha.isoformat(), "aviso": "Regenera el plan para que tenga en cuenta el cambio de calendario."}


@router.delete("/calendario/festivos/{fecha}")
def quitar_festivo(fecha: date, s: Session = Depends(get_sesion), u: UsuarioActual = Depends(requiere("recursos"))) -> dict:
    f = s.get(Festivo, fecha)
    if f is None:
        raise HTTPException(404, "Ese día no es festivo")
    auditar(s, u.usuario, "QUITAR_FESTIVO", "CALENDARIO", fecha.isoformat(), antes={"descripcion": f.descripcion})
    s.delete(f)
    return {"fecha": fecha.isoformat()}


class JornadaExtraIn(BaseModel):
    fecha: date
    turno: str
    secciones: list[str] | None = None
    motivo: str | None = None


@router.post("/calendario/jornadas-extra")
def nueva_jornada_extra(datos: JornadaExtraIn, s: Session = Depends(get_sesion), u: UsuarioActual = Depends(requiere("recursos"))) -> dict:
    if s.get(Turno, datos.turno) is None:
        raise HTTPException(400, f"Turno desconocido: {datos.turno}")
    j = JornadaExtra(fecha=datos.fecha, turno_codigo=datos.turno, secciones=datos.secciones or None, motivo=datos.motivo, creado_por=u.usuario)
    s.add(j)
    s.flush()
    auditar(s, u.usuario, "CREAR_JORNADA_EXTRA", "CALENDARIO", j.id, despues=datos.model_dump(mode="json"), motivo=datos.motivo)
    return {"id": j.id, "aviso": "Regenera el plan para aprovechar la jornada extra."}


@router.delete("/calendario/jornadas-extra/{jid}")
def quitar_jornada_extra(jid: int, s: Session = Depends(get_sesion), u: UsuarioActual = Depends(requiere("recursos"))) -> dict:
    j = s.get(JornadaExtra, jid)
    if j is None:
        raise HTTPException(404, "Jornada extra inexistente")
    auditar(s, u.usuario, "QUITAR_JORNADA_EXTRA", "CALENDARIO", jid, antes={"fecha": j.fecha.isoformat(), "turno": j.turno_codigo, "secciones": j.secciones})
    s.delete(j)
    return {"id": jid}
