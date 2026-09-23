"""Calendario laboral: festivos y jornadas extra (turnos fuera del calendario habitual)."""

from __future__ import annotations

from datetime import date, datetime

import pytest
from sqlalchemy import func, select

from hidral_plan.db import sesion
from hidral_plan.modelos import Festivo, JornadaExtra, Recurso
from hidral_plan.planificacion import servicio as sv
from hidral_plan.planificacion.modelo import cargar_instantanea

from .conftest import AHORA
from .generador_pdf import Aparato as ApGen
from .generador_pdf import OpcionesTanda, generar_tanda

SABADO = date(2026, 9, 26)
MARTES = date(2026, 9, 22)


def _minutos_recurso(s, codigo: str, dia: date) -> float:
    inst = cargar_instantanea(s, AHORA)
    r = next(x for x in inst.recursos.values() if x.codigo == codigo)
    return inst.ventanas_recurso(r).minutos(datetime.combine(dia, datetime.min.time()), datetime.combine(dia, datetime.max.time()))


def test_jornada_extra_abre_el_sabado_y_festivo_cierra_el_martes(fabrica):
    with sesion() as s:
        assert _minutos_recurso(s, "LASERTUB", SABADO) == 0
        assert _minutos_recurso(s, "LASERTUB", MARTES) > 0
        s.add(JornadaExtra(fecha=SABADO, turno_codigo="M", secciones=None, motivo="recuperar retraso"))
        s.add(Festivo(fecha=MARTES, descripcion="fiesta local"))
    with sesion() as s:
        assert _minutos_recurso(s, "LASERTUB", SABADO) > 0, "la jornada extra abre el sábado"
        assert _minutos_recurso(s, "LASERTUB", MARTES) == 0, "el festivo cierra el martes"


def test_jornada_extra_de_una_seccion_solo_afecta_a_esa_seccion(fabrica):
    with sesion() as s:
        lt = s.scalar(select(Recurso).where(Recurso.codigo == "LASERTUB"))
        otra = s.scalar(select(Recurso).where(Recurso.seccion_codigo != lt.seccion_codigo, Recurso.activo.is_(True)).limit(1))
        s.add(JornadaExtra(fecha=SABADO, turno_codigo="M", secciones=[lt.seccion_codigo]))
        otro_codigo = otra.codigo
    with sesion() as s:
        assert _minutos_recurso(s, "LASERTUB", SABADO) > 0
        assert _minutos_recurso(s, otro_codigo, SABADO) == 0
        # y los operarios que trabajan en esa sección también tienen el sábado
        inst = cargar_instantanea(s, AHORA)
        lt_p = next(x for x in inst.recursos.values() if x.codigo == "LASERTUB")
        ops = [o for o in inst.operarios.values() if "LASERTUB" in o.recursos and o.turno == "M"]
        assert ops and all(inst.ventanas_operario(o).minutos(datetime(2026, 9, 26), datetime(2026, 9, 27)) > 0 for o in ops)
        assert inst.ventanas_recurso(lt_p).minutos(datetime(2026, 9, 26), datetime(2026, 9, 27)) > 0


@pytest.fixture()
def con_plan(fabrica, importar, tmp_path):
    pdf = tmp_path / "t.pdf"
    generar_tanda(pdf, OpcionesTanda(aparatos=[ApGen("40001", ofs_relleno=12), ApGen("40002", ofs_relleno=12)]))
    importar(pdf)
    with sesion() as s:
        sv.generar_plan(s, "test", AHORA)
    return fabrica


def test_simular_turno_extra_y_aplicarlo(con_plan):
    esc = {"modo": "incremental", "turnos_extra": [{"fecha": SABADO.isoformat(), "turno": "M", "secciones": None}]}
    with sesion() as s:
        r = sv.simular_escenario(s, esc, "jefe", AHORA, guardar=False)
        assert any("Turno extra M el sáb 26/09" in d for d in r["escenario"])
        assert any("replanifica todo el horizonte" in d for d in r["escenario"])
        # la simulación no crea nada real
        assert s.scalar(select(func.count(JornadaExtra.id))) == 0
        plan_antes = sv.plan_activo(s).id
    with sesion() as s:
        a = sv.aplicar_escenario(s, esc, "planificador", AHORA, "recuperar semana")
        assert a["aplicado"] == ["turno extra M el 26/09 (toda la fábrica)"] and a["plan_id"] != plan_antes
    with sesion() as s:
        j = s.scalar(select(JornadaExtra))
        assert (j.fecha, j.turno_codigo, j.secciones, j.creado_por) == (SABADO, "M", None, "planificador")
        assert sv.plan_activo(s).id == a["plan_id"]


def test_los_supuestos_no_se_aplican(con_plan):
    with sesion() as s:
        lt = s.scalar(select(Recurso).where(Recurso.codigo == "LASERTUB"))
        with pytest.raises(ValueError, match="averías"):
            sv.aplicar_escenario(s, {"averias": [{"recurso_id": lt.id, "horas": 4}], "turnos_extra": [{"fecha": "2026-09-26", "turno": "M"}]}, "planificador", AHORA)
        with pytest.raises(ValueError, match="ninguna decisión"):
            sv.aplicar_escenario(s, {}, "planificador", AHORA)
