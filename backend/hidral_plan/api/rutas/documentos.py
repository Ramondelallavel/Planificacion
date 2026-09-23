"""Carga de documentos (asíncrona), progreso, validación y trazabilidad documental."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pymupdf
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ...config import ajustes
from ...ingesta.pipeline import registrar_documento
from ...modelos import Documento, IncidenciaDatos, OrdenFabricacion, Origen, PaginaDocumento, TrabajoProcesamiento
from ...modelos.comun import ahora
from ...modelos.enums import EstadoTrabajo
from ...servicios.auditoria import auditar
from ..deps import UsuarioActual, get_sesion, requiere

router = APIRouter(tags=["documentos"])
TROZO = 1024 * 1024


def _doc(d: Documento) -> dict:
    return {
        "id": d.id, "nombre": d.nombre, "hash": d.hash_sha256, "tamano_bytes": d.tamano_bytes, "paginas": d.num_paginas,
        "fecha_carga": d.fecha_carga.isoformat(), "usuario": d.usuario_carga, "estado": d.estado, "clave": d.clave_logica,
        "version": d.version, "documento_anterior_id": d.documento_anterior_id, "resumen": d.resumen,
        "fecha_fin": d.fecha_fin.isoformat() if d.fecha_fin else None,
    }


def _trabajo(t: TrabajoProcesamiento) -> dict:
    total = t.paginas_totales or 0
    c = {k: v for k, v in (t.contadores or {}).items() if k not in ("contexto", "pendientes", "aparatos_lista", "secciones_lista")}
    return {
        "id": t.id, "documento_id": t.documento_id, "estado": t.estado, "fase": t.fase, "paginas_procesadas": t.paginas_procesadas,
        "paginas_totales": total, "porcentaje": round(100 * t.paginas_procesadas / total, 1) if total else 0.0, "bloque_actual": t.bloque_actual,
        "bloques_totales": t.bloques_totales, "tamano_bloque": t.tamano_bloque, "eta_segundos": t.eta_segundos,
        "inicio": t.inicio.isoformat() if t.inicio else None, "fin": t.fin.isoformat() if t.fin else None, "contadores": c,
        "error": t.mensaje_error, "intentos": t.intentos,
    }


@router.post("/documentos", status_code=202)
async def cargar(fichero: UploadFile = File(...), s: Session = Depends(get_sesion), u: UsuarioActual = Depends(requiere("importar"))) -> dict:
    """Guarda el PDF por trozos (no se carga entero en memoria), detecta duplicados y encola el
    procesamiento. Devuelve inmediatamente el estado "En cola"."""
    if not (fichero.filename or "").lower().endswith(".pdf"):
        raise HTTPException(400, "Solo se admiten ficheros PDF")
    destino = Path(ajustes().almacen_dir) / "tmp"
    destino.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=destino, suffix=".pdf", delete=False) as tmp:
        while trozo := await fichero.read(TROZO):
            tmp.write(trozo)
        ruta = Path(tmp.name)
    s.close()
    r = registrar_documento(ruta, fichero.filename or "documento.pdf", u.usuario)
    return {
        "documento_id": r.documento_id, "trabajo_id": r.trabajo_id, "duplicado": r.duplicado, "nueva_version": r.nueva_version,
        "version": r.version, "mensaje": r.mensaje, "estado": "DUPLICADO" if r.duplicado else "En cola",
    }


@router.get("/documentos")
def listar(s: Session = Depends(get_sesion), _: UsuarioActual = Depends(requiere("ver"))) -> list[dict]:
    return [_doc(d) for d in s.scalars(select(Documento).order_by(Documento.id.desc()).limit(200))]


@router.get("/documentos/{doc_id}")
def detalle(doc_id: int, s: Session = Depends(get_sesion), _: UsuarioActual = Depends(requiere("ver"))) -> dict:
    d = s.get(Documento, doc_id)
    if d is None:
        raise HTTPException(404, "Documento inexistente")
    trabajos = [_trabajo(t) for t in s.scalars(select(TrabajoProcesamiento).where(TrabajoProcesamiento.documento_id == doc_id).order_by(TrabajoProcesamiento.id.desc()))]
    versiones = []
    if d.clave_logica:
        versiones = [
            {"id": v.id, "version": v.version, "estado": v.estado, "fecha_carga": v.fecha_carga.isoformat(), "nombre": v.nombre}
            for v in s.scalars(select(Documento).where(Documento.clave_logica == d.clave_logica).order_by(Documento.version))
        ]
    tipos = dict(s.execute(select(PaginaDocumento.tipo, func.count()).where(PaginaDocumento.documento_id == doc_id).group_by(PaginaDocumento.tipo)).all())
    return {**_doc(d), "trabajos": trabajos, "versiones": versiones, "tipos_pagina": tipos}


@router.get("/trabajos/{trabajo_id}")
def progreso(trabajo_id: int, s: Session = Depends(get_sesion), _: UsuarioActual = Depends(requiere("ver"))) -> dict:
    t = s.get(TrabajoProcesamiento, trabajo_id)
    if t is None:
        raise HTTPException(404, "Trabajo inexistente")
    return _trabajo(t)


@router.post("/trabajos/{trabajo_id}/cancelar")
def cancelar(trabajo_id: int, s: Session = Depends(get_sesion), u: UsuarioActual = Depends(requiere("importar"))) -> dict:
    t = s.get(TrabajoProcesamiento, trabajo_id)
    if t is None or t.estado not in (EstadoTrabajo.EN_COLA, EstadoTrabajo.PROCESANDO):
        raise HTTPException(400, "El trabajo no se puede cancelar")
    t.estado = EstadoTrabajo.CANCELADO
    t.fin = ahora()
    auditar(s, u.usuario, "CANCELAR_IMPORTACION", "DOCUMENTO", t.documento_id)
    return _trabajo(t)


@router.get("/documentos/{doc_id}/incidencias")
def incidencias(
    doc_id: int, severidad: str | None = None, tipo: str | None = None, estado: str | None = None, limite: int = 500,
    s: Session = Depends(get_sesion), _: UsuarioActual = Depends(requiere("ver")),
) -> list[dict]:
    q = select(IncidenciaDatos).where(IncidenciaDatos.documento_id == doc_id)
    if severidad:
        q = q.where(IncidenciaDatos.severidad == severidad)
    if tipo:
        q = q.where(IncidenciaDatos.tipo == tipo)
    if estado:
        q = q.where(IncidenciaDatos.estado == estado)
    orden = {"CRITICA": 0, "ERROR": 1, "ADVERTENCIA": 2, "INFO": 3}
    filas = list(s.scalars(q.limit(limite)))
    filas.sort(key=lambda i: (orden.get(i.severidad, 9), i.pagina or 0))
    return [
        {
            "id": i.id, "pagina": i.pagina, "tipo": i.tipo, "severidad": i.severidad, "mensaje": i.mensaje, "entidad_tipo": i.entidad_tipo,
            "entidad_ref": i.entidad_ref, "texto_origen": i.texto_origen, "alternativas": i.alternativas, "estado": i.estado,
            "resuelta_por": i.resuelta_por, "resolucion": i.resolucion,
        }
        for i in filas
    ]


class Revision(BaseModel):
    estado: str  # REVISADA | RESUELTA | IGNORADA | ABIERTA
    resolucion: str | None = None


@router.patch("/incidencias-datos/{inc_id}")
def revisar(inc_id: int, datos: Revision, s: Session = Depends(get_sesion), u: UsuarioActual = Depends(requiere("validar_datos"))) -> dict:
    i = s.get(IncidenciaDatos, inc_id)
    if i is None:
        raise HTTPException(404, "Incidencia inexistente")
    if datos.estado not in ("REVISADA", "RESUELTA", "IGNORADA", "ABIERTA"):
        raise HTTPException(400, "Estado no válido")
    if datos.estado in ("RESUELTA", "IGNORADA") and not datos.resolucion:
        raise HTTPException(400, "Indique cómo se ha resuelto o por qué se ignora")
    antes = i.estado
    i.estado, i.resolucion, i.resuelta_por = datos.estado, datos.resolucion, u.usuario
    auditar(s, u.usuario, "REVISION_DATOS", "INCIDENCIA_DATOS", i.id, antes={"estado": antes}, despues={"estado": i.estado, "resolucion": i.resolucion})
    return {"id": i.id, "estado": i.estado}


@router.get("/documentos/{doc_id}/paginas")
def paginas(doc_id: int, s: Session = Depends(get_sesion), _: UsuarioActual = Depends(requiere("ver"))) -> list[dict]:
    return [
        {"numero": p.numero, "bloque": p.bloque, "tipo": p.tipo, "metodo": p.metodo_extraccion, "caracteres": p.num_caracteres, "seccion": p.seccion_codigo, "grupo_hf": p.grupo_hf, "pagina_de": p.pagina_de, "ofs": p.ofs_detectadas, "avisos": p.avisos}
        for p in s.scalars(select(PaginaDocumento).where(PaginaDocumento.documento_id == doc_id).order_by(PaginaDocumento.numero))
    ]


@router.get("/documentos/{doc_id}/paginas/{numero}")
def pagina(doc_id: int, numero: int, s: Session = Depends(get_sesion), _: UsuarioActual = Depends(requiere("ver"))) -> dict:
    p = s.scalar(select(PaginaDocumento).where(PaginaDocumento.documento_id == doc_id, PaginaDocumento.numero == numero))
    if p is None:
        raise HTTPException(404, "Página inexistente")
    return {"numero": p.numero, "tipo": p.tipo, "bloque": p.bloque, "metodo": p.metodo_extraccion, "seccion": p.seccion_codigo, "grupo_hf": p.grupo_hf, "texto": p.texto, "ofs": p.ofs_detectadas}


@router.get("/documentos/{doc_id}/paginas/{numero}/imagen")
def imagen(doc_id: int, numero: int, dpi: int = 110, s: Session = Depends(get_sesion), _: UsuarioActual = Depends(requiere("ver"))) -> Response:
    """Render bajo demanda de UNA página (auditoría visual de la extracción)."""
    d = s.get(Documento, doc_id)
    if d is None or not d.num_paginas or not 1 <= numero <= d.num_paginas:
        raise HTTPException(404, "Página inexistente")
    with pymupdf.open(d.ruta_almacen) as doc:
        png = doc.load_page(numero - 1).get_pixmap(dpi=max(50, min(dpi, 200))).tobytes("png")
    return Response(png, media_type="image/png", headers={"Cache-Control": "private, max-age=3600"})


@router.get("/trazabilidad/{entidad}/{entidad_id}")
def trazabilidad(entidad: str, entidad_id: int, s: Session = Depends(get_sesion), _: UsuarioActual = Depends(requiere("ver"))) -> list[dict]:
    salida = []
    for o in s.scalars(select(Origen).where(Origen.entidad_tipo == entidad.upper(), Origen.entidad_id == entidad_id).order_by(Origen.id)):
        doc = s.get(Documento, o.documento_id) if o.documento_id else None
        salida.append(
            {
                "campo": o.campo, "fuente": o.fuente, "documento_id": o.documento_id, "documento": doc.nombre if doc else None,
                "clave_documento": doc.clave_logica if doc else None, "pagina": o.pagina, "bloque": o.bloque, "texto_origen": o.texto_origen,
                "detalle": o.detalle, "fecha": o.fecha.isoformat(),
            }
        )
    return salida


@router.get("/documentos/{doc_id}/ofs")
def ofs_documento(doc_id: int, s: Session = Depends(get_sesion), _: UsuarioActual = Depends(requiere("ver"))) -> list[dict]:
    return [
        {"id": o.id, "numero": o.numero, "seccion": o.seccion_codigo, "grupo_hf": o.grupo_hf, "paginas": o.paginas, "tiene_hoja": o.tiene_hoja}
        for o in s.scalars(select(OrdenFabricacion).where(OrdenFabricacion.documento_id == doc_id).order_by(OrdenFabricacion.numero))
    ]
