"""Pruebas unitarias del calendario, normalización, prioridad y restricciones."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta

from hidral_plan.ingesta.maquetacion import a_numero, parametros_a_dict
from hidral_plan.ingesta.normalizacion import semana_desde_corta
from hidral_plan.planificacion.calendario import Ocupacion, TurnoDef, Ventanas, repartir, restar, ventanas_turno
from hidral_plan.seguridad import emitir_token, hash_clave, leer_token, tiene_permiso, verificar_clave

LUNES = datetime(2026, 9, 21)
MANANA = TurnoDef("M", time(7), time(15), frozenset({0, 1, 2, 3, 4}), ((time(10), time(10, 20)),))


def test_numeros_espanoles_sin_adivinar():
    assert a_numero("1,5") == 1.5
    assert a_numero("2084,8") == 2084.8
    assert a_numero("71574") == 71574
    assert a_numero("1.284") == 1284
    assert a_numero("8.3") == 8.3
    assert a_numero("1x4410") is None
    assert a_numero("") is None and a_numero("abc") is None


def test_parametros():
    assert parametros_a_dict("R=2670 F=230 OpcGalvanizado=falso Color=") == {"R": "2670", "F": "230", "OpcGalvanizado": "falso", "Color": ""}


def test_semana_desde_s40_con_anio_de_emision():
    assert semana_desde_corta(40, date(2026, 9, 15))[0] == "202640"
    assert semana_desde_corta(2, date(2026, 12, 10))[0] == "202702"  # cambio de año documentado
    assert semana_desde_corta(40, None)[0] is None  # sin fecha no se inventa el año


def test_ventanas_de_turno_con_pausa_y_fin_de_semana():
    v = ventanas_turno(MANANA, LUNES, LUNES + timedelta(days=7))
    assert v[0] == (LUNES.replace(hour=7), LUNES.replace(hour=10)) and v[1] == (LUNES.replace(hour=10, minute=20), LUNES.replace(hour=15))
    assert len(v) == 10  # 5 días x 2 tramos
    assert all(a.weekday() < 5 for a, _ in v)


def test_repartir_parte_en_pausa_y_en_turno_siguiente():
    v = Ventanas(ventanas_turno(MANANA, LUNES, LUNES + timedelta(days=7)))
    tramos = repartir(v, LUNES.replace(hour=14), 120)
    assert tramos == [(LUNES.replace(hour=14), LUNES.replace(hour=15)), (LUNES.replace(day=22, hour=7), LUNES.replace(day=22, hour=8))]
    viernes = LUNES + timedelta(days=4)
    t2 = repartir(Ventanas(ventanas_turno(MANANA, LUNES, LUNES + timedelta(days=14))), viernes.replace(hour=14, minute=30), 60)
    assert t2[-1][1] == (LUNES + timedelta(days=7)).replace(hour=7, minute=30)  # salta el fin de semana


def test_restar_paradas():
    v = ventanas_turno(MANANA, LUNES, LUNES + timedelta(days=1))
    libre = restar(v, [(LUNES.replace(hour=8), LUNES.replace(hour=12))])
    assert libre == [(LUNES.replace(hour=7), LUNES.replace(hour=8)), (LUNES.replace(hour=12), LUNES.replace(hour=15))]


def test_ocupacion_detecta_conflictos():
    oc = Ocupacion()
    oc.agregar([(LUNES.replace(hour=8), LUNES.replace(hour=9))], 1)
    oc.agregar([(LUNES.replace(hour=11), LUNES.replace(hour=12))], 2)
    assert oc.primer_conflicto([(LUNES.replace(hour=8, minute=30), LUNES.replace(hour=10))]) is not None
    assert oc.primer_conflicto([(LUNES.replace(hour=9), LUNES.replace(hour=11))]) is None
    assert oc.primer_conflicto([(LUNES.replace(hour=10), LUNES.replace(hour=11, minute=1))]) is not None
    assert oc.anterior_id(LUNES.replace(hour=10)) == 1


def test_seguridad():
    h = hash_clave("secreta")
    assert verificar_clave("secreta", h) and not verificar_clave("otra", h)
    datos = leer_token(emitir_token("ana", "JEFE_EQUIPO", None))
    assert datos["u"] == "ana" and datos["r"] == "JEFE_EQUIPO"
    assert leer_token(emitir_token("ana", "OPERARIO", 1) + "x") is None
    assert tiene_permiso("PLANIFICADOR", "planificar") and not tiene_permiso("OPERARIO", "planificar")
    assert tiene_permiso("ADMINISTRADOR", "lo_que_sea") and not tiene_permiso("CONSULTA", "modificar_plan")
