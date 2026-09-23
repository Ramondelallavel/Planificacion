"""Pruebas con el PDF real de la tanda 2210 (se omiten si el fichero no está disponible)."""

from __future__ import annotations

import pytest
from sqlalchemy import func, select

from hidral_plan.db import sesion
from hidral_plan.modelos import (
    Aparato,
    Bulto,
    ComponenteBulto,
    DependenciaOF,
    Documento,
    IncidenciaDatos,
    LineaOF,
    OrdenFabricacion,
    Origen,
    PaginaDocumento,
    Tanda,
)
from hidral_plan.modelos.enums import EstadoProgramacion, Severidad
from hidral_plan.planificacion import servicio as sv

from .conftest import AHORA, PDF_REAL, plan_valido

pytestmark = pytest.mark.skipif(not PDF_REAL.exists(), reason="PDF real de ejemplo no disponible (ver tests/fixtures/README.md)")


@pytest.fixture()
def tanda_2210(fabrica, importar):
    r = importar(PDF_REAL)
    return r


def _of(s, numero: str) -> OrdenFabricacion:
    return s.scalar(select(OrdenFabricacion).where(OrdenFabricacion.numero == numero))


def _deps(s, numero: str) -> tuple[set[str], set[str]]:
    of = _of(s, numero)
    nums = dict(s.execute(select(OrdenFabricacion.id, OrdenFabricacion.numero)).all())
    pred = {nums[d.of_origen_id] for d in s.scalars(select(DependenciaOF).where(DependenciaOF.of_destino_id == of.id))}
    suc = {nums[d.of_destino_id] for d in s.scalars(select(DependenciaOF).where(DependenciaOF.of_origen_id == of.id))}
    return pred, suc


def test_estructura_de_la_tanda_2210(tanda_2210):
    with sesion() as s:
        d = s.get(Documento, tanda_2210.documento_id)
        assert d.num_paginas == 99 and d.clave_logica == "TANDA 2210"
        r = d.resumen
        assert r["ofs"] == 130 and r["aparatos"] == 2 and r["criticas"] == 0 and r["ciclos"] == 0
        t = s.scalar(select(Tanda))
        assert t.numero == "2210" and t.producto == "EH/DC-5000 | HO" and t.semana_codigo == "202640"
        assert [a.referencia for a in t.aparatos] == ["EH-36747", "EH-36760"]
        tipos = dict(s.execute(select(PaginaDocumento.tipo, func.count()).group_by(PaginaDocumento.tipo)).all())
        assert tipos == {"HOJA_GRUPO_HF": 74, "HOJA_CAB_PUERTAS": 4, "HOJA_LCH": 6, "LISTA_MATERIALES": 11, "PACKING_LIST": 2, "SIN_TEXTO": 2}
        # no hay filas sin interpretar en las hojas; las 2 páginas sin texto quedan señaladas
        assert s.scalar(select(func.count(IncidenciaDatos.id)).where(IncidenciaDatos.tipo == "FILA_NO_INTERPRETADA")) == 0
        assert {i.pagina for i in s.scalars(select(IncidenciaDatos).where(IncidenciaDatos.tipo == "PAGINA_SIN_TEXTO"))} == {48, 50}


def test_of_917251_montaje_guia(tanda_2210):
    with sesion() as s:
        of = _of(s, "917251")
        assert (of.seccion_codigo, of.grupo_hf, of.modo, of.semana_codigo) == ("MF", "MONTAJE GUIAS-ESTRIBO-CABEZAL", "Conjunta-Pedido", "202640")
        assert s.get(Aparato, of.aparato_id).referencia == "EH-36747"
        pred, suc = _deps(s, "917251")
        assert {"917317", "917200"} <= pred and suc == {"917255"}
        salida = s.scalar(select(LineaOF).where(LineaOF.of_id == of.id, LineaOF.tipo == "SALIDA"))
        assert salida.articulo_codigo == "3001000/4" and salida.parametros_dict["LG1"] == "3245" and salida.orden_ref == "917255"
        # trazabilidad: documento + página + texto de origen
        o = s.scalar(select(Origen).where(Origen.entidad_tipo == "OF", Origen.entidad_id == of.id))
        assert o.pagina == 1 and "917251" in o.texto_origen


def test_lch_y_plegado(tanda_2210):
    with sesion() as s:
        lch = _of(s, "917332")
        assert lch.seccion_codigo == "LCH" and lch.grupo_conj == "SG6 NCX PUERTAS EH" and lch.semana_codigo == "202640"
        assert lch.estado_programacion == EstadoProgramacion.PENDIENTE_PROGRAMACION
        piezas = list(s.scalars(select(LineaOF).where(LineaOF.of_id == lch.id)))
        assert len(piezas) == 18
        p = next(p for p in piezas if p.posicion == "1027")
        assert (p.articulo_codigo, p.material, p.espesor_mm, p.orden_plegado, p.orden_ref) == ("7615105/7", "DC01", 1.5, "917325", "917280")
        pleg = _of(s, "917325")
        assert not pleg.tiene_hoja and pleg.operaciones[0].tipo == "PLEGADO"
        pred, _ = _deps(s, "917280")
        assert "917325" in pred


def test_lasertub_y_consumos(tanda_2210):
    with sesion() as s:
        of = _of(s, "917245")
        assert of.programa_codigo == "PL025286/A" and of.programa_descripcion == "CORTE-TALADRO LASERTUB"
        assert of.estado_programacion == EstadoProgramacion.PROGRAMADA
        assert of.consumos[0]["articulo"] == "1202114/1" and of.consumos[0]["total"] == 71574
        assert of.operaciones[0].recurso_preferido == "LASERTUB"
        pieza = s.scalar(select(LineaOF).where(LineaOF.of_id == of.id, LineaOF.id_pieza == "EH-36747-0305"))
        assert pieza.detalle_corte == "2x235" and pieza.cantidad == 2


def test_bultos_de_lista_de_materiales_packing_y_cab(tanda_2210):
    with sesion() as s:
        ap = s.scalar(select(Aparato).where(Aparato.numero_control == "36747"))
        principales = [b for b in ap.bultos if b.padre_id is None]
        assert [b.numero for b in principales] == ["1", "2", "3", "4", "5", "6"]
        b6 = next(b for b in principales if b.numero == "6")
        assert b6.descripcion == "CAJON PUERTAS BATIENTES 1H" and b6.peso_kg == 239
        assert _of(s, "917194").id == b6.of_id  # montaje-embalaje de puertas → bulto 6 (hoja CAB)
        assert {f.split(" ")[0] for f in b6.fuentes} == {"HOJA_CAB", "LISTA_MATERIALES", "PACKING_LIST"}
        ap2 = s.scalar(select(Aparato).where(Aparato.numero_control == "36760"))
        assert len([b for b in ap2.bultos if b.padre_id is None]) == 11
        assert ap.cliente and ap.su_referencia == "73347241"
        assert s.scalar(select(func.count(ComponenteBulto.id))) > 250
        assert s.scalar(select(func.count(Bulto.id))) == 36


def test_plan_sobre_la_tanda_real(tanda_2210):
    with sesion() as s:
        r = sv.generar_plan(s, "test", AHORA)
        assert r["kpis"]["planificadas"] > 100
    with sesion() as s:
        plan = sv.plan_activo(s)
        assert not plan_valido(sv.asignaciones_de(s, plan).values())
        # PLPINO no está configurada: sus OF no se inventan, quedan como no planificables con motivo
        motivos = {n["of"]: n["motivo"] for n in plan.no_planificadas}
        assert motivos.get("917217") == "SIN_RECURSO"
        assert motivos.get("917252") == "PREDECESORA_NO_PLANIFICABLE"
        # al informar la fecha prevista de las OF externas, lo que depende de ellas se planifica
        for n in ("917216", "917217", "917220", "917218", "917219"):
            sv.informar_disponibilidad(s, _of(s, n).id, AHORA.replace(hour=12), "USUARIO", "test")
        r2 = sv.generar_plan(s, "test", AHORA)
        assert r2["no_planificadas"] < len(plan.no_planificadas)
    with sesion() as s:
        plan2 = sv.plan_activo(s)
        assert "917252" not in {n["of"] for n in plan2.no_planificadas}
        assert s.scalar(select(func.count(IncidenciaDatos.id)).where(IncidenciaDatos.severidad == Severidad.CRITICA)) == 0
