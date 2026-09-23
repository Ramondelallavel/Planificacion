"""Visor de estructura: TANDA → APARATOS → BULTOS / OF → OPERACIONES, con origen de cada dato."""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from ...modelos import (
    Aparato,
    AsignacionPlan,
    Bulto,
    DependenciaOF,
    IncidenciaDatos,
    LineaOF,
    OFAparato,
    Operacion,
    OrdenFabricacion,
    ProgramaCNC,
    Recurso,
    Tanda,
)
from ...planificacion import servicio as sv
from ...servicios.auditoria import auditar
from ..deps import UsuarioActual, get_sesion, requiere

router = APIRouter(tags=["estructura"])


def _of_resumen(o: OrdenFabricacion) -> dict:
    return {
        "id": o.id, "numero": o.numero, "seccion": o.seccion_codigo, "grupo_hf": o.grupo_hf, "descripcion": o.descripcion, "modo": o.modo,
        "semana": o.semana_codigo, "estado": o.estado, "estado_programacion": o.estado_programacion, "programa": o.programa_codigo,
        "horas_estimadas": o.horas_estimadas, "horas_reales": o.horas_reales, "riesgo": o.riesgo_nivel, "urgente": o.urgente,
        "bloqueada": o.bloqueada_manual, "tiene_hoja": o.tiene_hoja, "aparato_id": o.aparato_id, "tanda_id": o.tanda_id,
        "inicio_previsto": o.fecha_prevista_inicio.isoformat() if o.fecha_prevista_inicio else None,
        "fin_previsto": o.fecha_prevista_fin.isoformat() if o.fecha_prevista_fin else None,
        "material_disponible": o.material_disponible, "disponible_prevista": o.disponible_prevista.isoformat() if o.disponible_prevista else None,
        "prioridad_ortems": o.prioridad_ortems, "paginas": o.paginas,
    }


@router.get("/tandas")
def tandas(s: Session = Depends(get_sesion), _: UsuarioActual = Depends(requiere("ver"))) -> list[dict]:
    salida = []
    for t in s.scalars(select(Tanda).order_by(Tanda.semana_codigo, Tanda.numero)):
        n_of = s.scalar(select(func.count(OrdenFabricacion.id)).where(OrdenFabricacion.tanda_id == t.id, OrdenFabricacion.tiene_hoja.is_(True)))
        terminadas = s.scalar(select(func.count(OrdenFabricacion.id)).where(OrdenFabricacion.tanda_id == t.id, OrdenFabricacion.estado.in_(["TERMINADA", "VALIDADA"])))
        salida.append(
            {
                "id": t.id, "numero": t.numero, "producto": t.producto, "semana": t.semana_codigo, "estado": t.estado, "riesgo": t.riesgo_nivel,
                "motivos": t.riesgo_motivos, "progreso": t.progreso, "carga_restante_h": t.carga_restante_h, "aparatos": len(t.aparatos),
                "ofs": n_of, "ofs_terminadas": terminadas, "incluida_en_plan": t.incluida_en_plan, "documento_id": t.documento_id,
            }
        )
    return salida


class CambioTanda(BaseModel):
    incluida_en_plan: bool | None = None
    estado: str | None = None
    motivo: str | None = None


@router.patch("/tandas/{tanda_id}")
def cambiar_tanda(tanda_id: int, datos: CambioTanda, s: Session = Depends(get_sesion), u: UsuarioActual = Depends(requiere("planificar"))) -> dict:
    t = s.get(Tanda, tanda_id)
    if t is None:
        raise HTTPException(404, "Tanda inexistente")
    antes = {"incluida_en_plan": t.incluida_en_plan, "estado": t.estado}
    if datos.incluida_en_plan is not None:
        t.incluida_en_plan = datos.incluida_en_plan
    if datos.estado:
        t.estado = datos.estado
    auditar(s, u.usuario, "CAMBIO_TANDA", "TANDA", t.numero, antes=antes, despues={"incluida_en_plan": t.incluida_en_plan, "estado": t.estado}, motivo=datos.motivo)
    return {"id": t.id}


@router.get("/tandas/{tanda_id}")
def tanda(tanda_id: int, s: Session = Depends(get_sesion), _: UsuarioActual = Depends(requiere("ver"))) -> dict:
    t = s.get(Tanda, tanda_id)
    if t is None:
        raise HTTPException(404, "Tanda inexistente")
    aparatos = []
    for a in t.aparatos:
        n_of = s.scalar(select(func.count(OFAparato.of_id)).where(OFAparato.aparato_id == a.id))
        aparatos.append(
            {
                "id": a.id, "referencia": a.referencia, "numero_control": a.numero_control, "producto": a.producto, "cliente": a.cliente,
                "semana": a.semana_codigo, "estado": a.estado, "riesgo": a.riesgo_nivel, "motivos": a.riesgo_motivos, "ofs": n_of,
                "bultos": sum(1 for b in a.bultos if b.padre_id is None), "carga_restante_h": a.carga_restante_h,
                "fin_previsto": a.fin_previsto.isoformat() if a.fin_previsto else None, "su_referencia": a.su_referencia,
            }
        )
    secciones = [
        {"seccion": sec, "ofs": n, "horas": round(h or 0, 2)}
        for sec, n, h in s.execute(
            select(OrdenFabricacion.seccion_codigo, func.count(OrdenFabricacion.id), func.sum(OrdenFabricacion.horas_estimadas))
            .where(OrdenFabricacion.tanda_id == tanda_id)
            .group_by(OrdenFabricacion.seccion_codigo)
            .order_by(OrdenFabricacion.seccion_codigo)
        )
    ]
    return {
        "id": t.id, "numero": t.numero, "producto": t.producto, "semana": t.semana_codigo, "estado": t.estado, "riesgo": t.riesgo_nivel,
        "motivos": t.riesgo_motivos, "progreso": t.progreso, "carga_restante_h": t.carga_restante_h, "aparatos": aparatos, "secciones": secciones,
    }


@router.get("/aparatos/{ap_id}")
def aparato(ap_id: int, s: Session = Depends(get_sesion), _: UsuarioActual = Depends(requiere("ver"))) -> dict:
    a = s.get(Aparato, ap_id)
    if a is None:
        raise HTTPException(404, "Aparato inexistente")
    of_ids = [i for (i,) in s.execute(select(OFAparato.of_id).where(OFAparato.aparato_id == ap_id))]
    ofs = [_of_resumen(o) for o in s.scalars(select(OrdenFabricacion).where(OrdenFabricacion.id.in_(of_ids)).order_by(OrdenFabricacion.seccion_codigo, OrdenFabricacion.numero))]
    bultos = []
    for b in a.bultos:
        bultos.append(
            {
                "id": b.id, "numero": b.numero, "padre_id": b.padre_id, "codigo": b.codigo, "descripcion": b.descripcion, "largo_mm": b.largo_mm,
                "ancho_mm": b.ancho_mm, "alto_mm": b.alto_mm, "peso_kg": b.peso_kg, "estado": b.estado, "fuentes": b.fuentes, "of_id": b.of_id,
                "componentes": [
                    {"articulo": c.articulo_codigo, "descripcion": c.descripcion, "parametros": c.parametros, "cantidad": c.cantidad, "pagina": c.pagina, "traduccion": c.traduccion}
                    for c in b.componentes
                ],
            }
        )
    return {
        "id": a.id, "referencia": a.referencia, "numero_control": a.numero_control, "tipo": a.tipo, "producto": a.producto, "cliente": a.cliente,
        "su_referencia": a.su_referencia, "ffp": a.ffp, "embalaje": a.embalaje, "semana": a.semana_codigo, "estado": a.estado, "riesgo": a.riesgo_nivel,
        "motivos": a.riesgo_motivos, "tanda_id": a.tanda_id, "fin_previsto": a.fin_previsto.isoformat() if a.fin_previsto else None,
        "carga_restante_h": a.carga_restante_h, "ofs": ofs, "bultos": bultos,
    }


@router.get("/ofs")
def ofs(
    tanda_id: int | None = None, aparato_id: int | None = None, seccion: str | None = None, estado: str | None = None, riesgo: str | None = None,
    q: str | None = None, limite: int = 200, desplazamiento: int = 0, s: Session = Depends(get_sesion), _: UsuarioActual = Depends(requiere("ver")),
) -> dict:
    consulta = select(OrdenFabricacion)
    if tanda_id:
        consulta = consulta.where(OrdenFabricacion.tanda_id == tanda_id)
    if aparato_id:
        consulta = consulta.where(OrdenFabricacion.id.in_(select(OFAparato.of_id).where(OFAparato.aparato_id == aparato_id)))
    if seccion:
        consulta = consulta.where(OrdenFabricacion.seccion_codigo == seccion)
    if estado:
        consulta = consulta.where(OrdenFabricacion.estado == estado)
    if riesgo:
        consulta = consulta.where(OrdenFabricacion.riesgo_nivel == riesgo)
    if q:
        patron = f"%{q}%"
        consulta = consulta.where(or_(OrdenFabricacion.numero.like(patron), OrdenFabricacion.descripcion.like(patron), OrdenFabricacion.grupo_hf.like(patron)))
    total = s.scalar(select(func.count()).select_from(consulta.subquery()))
    filas = s.scalars(consulta.order_by(OrdenFabricacion.fecha_prevista_inicio.is_(None), OrdenFabricacion.fecha_prevista_inicio, OrdenFabricacion.numero).offset(desplazamiento).limit(min(limite, 1000)))
    return {"total": total, "items": [_of_resumen(o) for o in filas]}


@router.get("/ofs/{of_id}")
def of_detalle(of_id: int, s: Session = Depends(get_sesion), _: UsuarioActual = Depends(requiere("ver"))) -> dict:
    o = s.get(OrdenFabricacion, of_id)
    if o is None:
        raise HTTPException(404, "OF inexistente")
    numeros = {}

    def num(i: int) -> dict:
        if i not in numeros:
            x = s.get(OrdenFabricacion, i)
            numeros[i] = {"id": i, "numero": x.numero if x else str(i), "seccion": x.seccion_codigo if x else None, "estado": x.estado if x else None, "grupo_hf": x.grupo_hf if x else None}
        return numeros[i]

    predecesoras = [{**num(d.of_origen_id), "tipo": d.tipo, "fuente": d.fuente, "evidencias": d.evidencias} for d in s.scalars(select(DependenciaOF).where(DependenciaOF.of_destino_id == of_id, DependenciaOF.activa.is_(True)))]
    sucesoras = [{**num(d.of_destino_id), "tipo": d.tipo, "fuente": d.fuente, "evidencias": d.evidencias} for d in s.scalars(select(DependenciaOF).where(DependenciaOF.of_origen_id == of_id, DependenciaOF.activa.is_(True)))]
    plan = sv.plan_activo(s)
    asignaciones = {}
    if plan:
        for a in s.scalars(select(AsignacionPlan).where(AsignacionPlan.plan_id == plan.id, AsignacionPlan.of_id == of_id)):
            r = s.get(Recurso, a.recurso_id) if a.recurso_id else None
            asignaciones[a.operacion_id] = {"inicio": a.inicio.isoformat(), "fin": a.fin.isoformat(), "recurso": r.codigo if r else None, "operario_id": a.operario_id, "explicacion": a.explicacion, "bloqueada": a.bloqueada, "provisional": a.provisional}
    no_plan = {n["operacion_id"]: n for n in (plan.no_planificadas or [])} if plan else {}
    operaciones = [
        {
            "id": op.id, "secuencia": op.secuencia, "tipo": op.tipo, "descripcion": op.descripcion, "seccion": op.seccion_codigo, "recurso_preferido": op.recurso_preferido,
            "duracion_estimada_min": op.duracion_estimada_min, "duracion_real_min": op.duracion_real_min, "origen_duracion": op.origen_duracion, "estado": op.estado,
            "requiere_programa": op.requiere_programa, "cantidad": op.cantidad, "cantidad_hecha": op.cantidad_hecha, "fuente": op.fuente, "familia_setup": op.familia_setup,
            "plan": asignaciones.get(op.id), "no_planificada": no_plan.get(op.id),
        }
        for op in o.operaciones
    ]
    lineas = [
        {
            "id": ln.id, "tipo": ln.tipo, "articulo": ln.articulo_codigo, "descripcion": ln.articulo_descripcion, "posicion": ln.posicion, "id_pieza": ln.id_pieza,
            "parametros": ln.parametros, "cantidad": ln.cantidad, "cantidad_texto": ln.cantidad_texto, "detalle_corte": ln.detalle_corte, "material": ln.material,
            "espesor_mm": ln.espesor_mm, "largo_mm": ln.largo_mm, "ancho_mm": ln.ancho_mm, "numero_control": ln.numero_control, "semana": ln.semana_codigo,
            "seccion_ref": ln.seccion_ref, "orden_ref": ln.orden_ref, "orden_plegado": ln.orden_plegado, "operaciones_marcadas": ln.operaciones_marcadas,
            "pagina": ln.pagina, "texto_origen": ln.texto_origen,
        }
        for ln in s.scalars(select(LineaOF).where(LineaOF.of_id == of_id).order_by(LineaOF.id))
    ]
    aparatos = [
        {"id": a.id, "referencia": a.referencia, "lineas": rel.lineas}
        for rel, a in s.execute(select(OFAparato, Aparato).join(Aparato, Aparato.id == OFAparato.aparato_id).where(OFAparato.of_id == of_id))
    ]
    incid = [
        {"id": i.id, "tipo": i.tipo, "severidad": i.severidad, "mensaje": i.mensaje, "pagina": i.pagina, "estado": i.estado}
        for i in s.scalars(select(IncidenciaDatos).where(IncidenciaDatos.entidad_ref == o.numero))
    ]
    programas = [{"codigo": p.codigo, "fuente": p.fuente, "estado": p.estado, "recurso": p.recurso_codigo, "registrado": p.registrado.isoformat(), "por": p.registrado_por} for p in s.scalars(select(ProgramaCNC).where(ProgramaCNC.of_id == of_id))]
    riesgo = ((plan.riesgos or {}).get("ofs", {}) if plan else {}).get(str(of_id))
    return {
        **_of_resumen(o), "seccion_completa": o.seccion_completa, "grupo_conj": o.grupo_conj, "consumos": o.consumos, "documento_id": o.documento_id,
        "fuente": o.fuente, "parametros_extra": o.parametros_extra, "aparatos": aparatos, "operaciones": operaciones, "lineas": lineas,
        "predecesoras": predecesoras, "sucesoras": sucesoras, "incidencias_datos": incid, "programas": programas, "riesgo_detalle": riesgo,
    }


class CambioOF(BaseModel):
    urgente: bool | None = None
    bloqueada: bool | None = None
    material_disponible: bool | None = None
    material_disponible_desde: datetime | None = None
    disponible_prevista: datetime | None = None
    prioridad_ortems: float | None = None
    motivo: str


@router.patch("/ofs/{of_id}")
def cambiar_of(of_id: int, datos: CambioOF, s: Session = Depends(get_sesion), u: UsuarioActual = Depends(requiere("modificar_plan"))) -> dict:
    o = s.get(OrdenFabricacion, of_id)
    if o is None:
        raise HTTPException(404, "OF inexistente")
    antes = {"urgente": o.urgente, "bloqueada": o.bloqueada_manual, "material_disponible": o.material_disponible, "disponible_prevista": o.disponible_prevista.isoformat() if o.disponible_prevista else None, "prioridad_ortems": o.prioridad_ortems}
    campos = datos.model_dump(exclude_unset=True)
    if "urgente" in campos:
        o.urgente = bool(datos.urgente)
    if "bloqueada" in campos:
        o.bloqueada_manual = bool(datos.bloqueada)
    if "material_disponible" in campos:
        o.material_disponible = datos.material_disponible
        o.material_disponible_desde = datos.material_disponible_desde
    if "disponible_prevista" in campos:
        sv.informar_disponibilidad(s, of_id, datos.disponible_prevista, "USUARIO", u.usuario, datos.motivo)
    if "prioridad_ortems" in campos:
        o.prioridad_ortems = datos.prioridad_ortems
    auditar(s, u.usuario, "CAMBIO_OF", "OF", o.numero, antes=antes, despues={k: (v.isoformat() if isinstance(v, datetime) else v) for k, v in campos.items()}, motivo=datos.motivo)
    return _of_resumen(o)


class Programa(BaseModel):
    codigo: str
    recurso_codigo: str | None = None
    notas: str | None = None


@router.post("/ofs/{of_id}/programa")
def programa(of_id: int, datos: Programa, s: Session = Depends(get_sesion), u: UsuarioActual = Depends(requiere("modificar_plan"))) -> dict:
    return sv.registrar_programa(s, of_id, datos.codigo, u.usuario, datos.recurso_codigo, datos.notas)


@router.get("/operaciones/{op_id}")
def operacion(op_id: int, s: Session = Depends(get_sesion), _: UsuarioActual = Depends(requiere("ver"))) -> dict:
    op = s.get(Operacion, op_id)
    if op is None:
        raise HTTPException(404, "Operación inexistente")
    return {"id": op.id, "of_id": op.of_id, "tipo": op.tipo, "estado": op.estado, "duracion_estimada_min": op.duracion_estimada_min, "origen_duracion": op.origen_duracion}


@router.get("/ofs/{of_id}/grafo")
def grafo(of_id: int, profundidad: int = 2, s: Session = Depends(get_sesion), _: UsuarioActual = Depends(requiere("ver"))) -> dict:
    """Subgrafo de dependencias alrededor de una OF (para el visor de relaciones)."""
    nodos: dict[int, dict] = {}
    aristas: list[dict] = []
    frontera = {of_id}
    vistos: set[int] = set()
    for _ in range(max(1, min(profundidad, 5))):
        nueva: set[int] = set()
        for d in s.scalars(select(DependenciaOF).where(or_(DependenciaOF.of_origen_id.in_(frontera), DependenciaOF.of_destino_id.in_(frontera)), DependenciaOF.activa.is_(True))):
            clave = (d.of_origen_id, d.of_destino_id)
            if clave not in vistos:
                vistos.add(clave)
                aristas.append({"origen": d.of_origen_id, "destino": d.of_destino_id, "tipo": d.tipo})
            nueva |= {d.of_origen_id, d.of_destino_id}
        frontera = nueva - set(nodos)
        for i in nueva:
            if i not in nodos:
                x = s.get(OrdenFabricacion, i)
                nodos[i] = {"id": i, "numero": x.numero, "seccion": x.seccion_codigo, "grupo_hf": x.grupo_hf, "estado": x.estado, "riesgo": x.riesgo_nivel, "tiene_hoja": x.tiene_hoja}
    if of_id not in nodos:
        x = s.get(OrdenFabricacion, of_id)
        nodos[of_id] = {"id": of_id, "numero": x.numero, "seccion": x.seccion_codigo, "grupo_hf": x.grupo_hf, "estado": x.estado, "riesgo": x.riesgo_nivel, "tiene_hoja": x.tiene_hoja}
    return {"nodos": list(nodos.values()), "aristas": aristas}


@router.get("/bultos/{bulto_id}")
def bulto(bulto_id: int, s: Session = Depends(get_sesion), _: UsuarioActual = Depends(requiere("ver"))) -> dict:
    b = s.get(Bulto, bulto_id)
    if b is None:
        raise HTTPException(404, "Bulto inexistente")
    return {"id": b.id, "numero": b.numero, "descripcion": b.descripcion, "componentes": len(b.componentes), "fuentes": b.fuentes}


