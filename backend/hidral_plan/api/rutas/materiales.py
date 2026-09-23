"""Materiales: stock, entradas previstas y disponibilidad de material de las OF."""

from __future__ import annotations

import csv
import io
from datetime import datetime

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ...modelos import EntradaMaterial, Material
from ...modelos.comun import ahora as reloj
from ...planificacion import servicio as sv
from ...servicios import materiales as mt
from ...servicios.auditoria import auditar
from ..deps import UsuarioActual, ahora, get_sesion, requiere

router = APIRouter(prefix="/materiales", tags=["materiales"])


@router.get("")
def listado(s: Session = Depends(get_sesion), _: UsuarioActual = Depends(requiere("ver"))) -> dict:
    return mt.listado(s, ahora())


@router.get("/detalle")
def detalle(codigo: str, s: Session = Depends(get_sesion), _: UsuarioActual = Depends(requiere("ver"))) -> dict:
    return mt.detalle(s, codigo, ahora())


class MaterialIn(BaseModel):
    codigo: str
    descripcion: str | None = None
    unidad: str | None = None
    stock: float | None = None
    controlado: bool | None = None
    plazo_dias: int | None = None
    notas: str | None = None


def _json(m: Material) -> dict:
    return {"codigo": m.codigo, "descripcion": m.descripcion, "unidad": m.unidad, "stock": m.stock, "controlado": m.controlado, "plazo_dias": m.plazo_dias, "notas": m.notas}


@router.post("")
def guardar(datos: MaterialIn, s: Session = Depends(get_sesion), u: UsuarioActual = Depends(requiere("recursos"))) -> dict:
    """Alta o cambio de un material (por código de artículo). Dar stock empieza a controlarlo."""
    codigo = datos.codigo.strip()
    if not codigo:
        raise HTTPException(400, "Falta el código del material")
    if datos.stock is not None and datos.stock < 0:
        raise HTTPException(400, "El stock no puede ser negativo")
    m = s.get(Material, codigo)
    antes = _json(m) if m else None
    if m is None:
        m = Material(codigo=codigo, unidad="ud", stock=0.0, controlado=True)
        s.add(m)
    campos = datos.model_dump(exclude_unset=True, exclude={"codigo"})
    for k, v in campos.items():
        if k == "unidad" and not v:
            continue
        setattr(m, k, v)
    m.actualizado, m.actualizado_por = reloj(), u.usuario
    s.flush()
    auditar(s, u.usuario, "CAMBIO_MATERIAL" if antes else "ALTA_MATERIAL", "MATERIAL", codigo, antes=antes, despues=_json(m))
    return _json(m)


@router.delete("")
def quitar(codigo: str, s: Session = Depends(get_sesion), u: UsuarioActual = Depends(requiere("recursos"))) -> dict:
    """Deja de controlar un material (se borran su stock y sus entradas)."""
    m = s.get(Material, codigo)
    if m is None:
        raise HTTPException(404, "Material no registrado")
    antes = _json(m)
    s.delete(m)
    auditar(s, u.usuario, "QUITAR_MATERIAL", "MATERIAL", codigo, antes=antes)
    return {"codigo": codigo}


class EntradaIn(BaseModel):
    codigo: str
    cantidad: float
    fecha_prevista: datetime
    referencia: str | None = None


@router.post("/entradas")
def nueva_entrada(datos: EntradaIn, s: Session = Depends(get_sesion), u: UsuarioActual = Depends(requiere("recursos"))) -> dict:
    if datos.cantidad <= 0:
        raise HTTPException(400, "La cantidad tiene que ser mayor que cero")
    m = s.get(Material, datos.codigo)
    if m is None:
        m = Material(codigo=datos.codigo, unidad="ud", stock=0.0, controlado=True, actualizado_por=u.usuario)
        s.add(m)
    e = EntradaMaterial(material_codigo=m.codigo, cantidad=datos.cantidad, fecha_prevista=datos.fecha_prevista, referencia=datos.referencia, creado_por=u.usuario)
    s.add(e)
    s.flush()
    auditar(s, u.usuario, "ENTRADA_MATERIAL_PREVISTA", "MATERIAL", m.codigo, despues={"cantidad": datos.cantidad, "fecha": datos.fecha_prevista.isoformat(), "referencia": datos.referencia})
    return {"id": e.id}


@router.post("/entradas/{eid}/recibir")
def recibir(eid: int, s: Session = Depends(get_sesion), u: UsuarioActual = Depends(requiere("recursos"))) -> dict:
    e = s.get(EntradaMaterial, eid)
    if e is None:
        raise HTTPException(404, "Entrada inexistente")
    if e.recibida:
        raise HTTPException(409, "Esa entrada ya se recibió")
    e.recibida, e.recibida_en = True, reloj()
    e.material.stock = (e.material.stock or 0) + e.cantidad
    auditar(s, u.usuario, "RECIBIR_MATERIAL", "MATERIAL", e.material_codigo, despues={"cantidad": e.cantidad, "stock": e.material.stock})
    return {"codigo": e.material_codigo, "stock": e.material.stock}


@router.delete("/entradas/{eid}")
def anular_entrada(eid: int, s: Session = Depends(get_sesion), u: UsuarioActual = Depends(requiere("recursos"))) -> dict:
    e = s.get(EntradaMaterial, eid)
    if e is None:
        raise HTTPException(404, "Entrada inexistente")
    codigo = e.material_codigo
    s.delete(e)
    auditar(s, u.usuario, "ANULAR_ENTRADA_MATERIAL", "MATERIAL", codigo, antes={"cantidad": e.cantidad, "fecha": e.fecha_prevista.isoformat()})
    return {"id": eid}


@router.post("/calcular")
def calcular(replanificar: bool = True, s: Session = Depends(get_sesion), u: UsuarioActual = Depends(requiere("planificar"))) -> dict:
    """Aplica stock y entradas a las OF y, si se pide, regenera el plan con esa disponibilidad."""
    r = mt.calcular(s, u.usuario, ahora())
    if replanificar:
        p = sv.generar_plan(s, u.usuario, ahora(), "Plan con disponibilidad de materiales", motivo="Recalculada la disponibilidad de materiales")
        r["plan_id"] = p["plan_id"]
        r["no_planificadas"] = p["no_planificadas"]
    return r


@router.post("/importar")
async def importar(fichero: UploadFile = File(...), s: Session = Depends(get_sesion), u: UsuarioActual = Depends(requiere("recursos"))) -> dict:
    """CSV con columnas codigo;descripcion;unidad;stock (separador ; o ,; decimales con coma o punto)."""
    texto = (await fichero.read()).decode("utf-8-sig", errors="replace")
    dialecto = csv.Sniffer().sniff(texto.splitlines()[0] if texto else "codigo;stock", delimiters=";,\t")
    filas = list(csv.DictReader(io.StringIO(texto), dialect=dialecto))
    hechos, errores = 0, []
    for i, f in enumerate(filas, start=2):
        f = {(k or "").strip().lower(): (v or "").strip() for k, v in f.items()}
        codigo = f.get("codigo") or f.get("código") or f.get("articulo") or f.get("artículo")
        if not codigo:
            errores.append(f"fila {i}: sin código")
            continue
        try:
            stock = float(f.get("stock", "0").replace(".", "").replace(",", ".")) if "," in f.get("stock", "") else float(f.get("stock") or 0)
        except ValueError:
            errores.append(f"fila {i}: stock «{f.get('stock')}» no es un número")
            continue
        m = s.get(Material, codigo) or Material(codigo=codigo, controlado=True)
        m.stock = stock
        m.descripcion = f.get("descripcion") or f.get("descripción") or m.descripcion
        m.unidad = f.get("unidad") or m.unidad or "ud"
        m.actualizado, m.actualizado_por = reloj(), u.usuario
        s.add(m)
        hechos += 1
    auditar(s, u.usuario, "IMPORTAR_STOCK", "MATERIAL", None, despues={"fichero": fichero.filename, "materiales": hechos, "errores": len(errores)})
    return {"materiales": hechos, "errores": errores[:20]}
