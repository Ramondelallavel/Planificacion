"""Casos de prueba obligatorios A–P del pliego (punto 56)."""

from __future__ import annotations

import tracemalloc
from datetime import datetime, timedelta

import pytest
from sqlalchemy import func, select

from hidral_plan.db import sesion
from hidral_plan.ingesta.pipeline import procesar_sincrono
from hidral_plan.modelos import (
    Aparato,
    AsignacionPlan,
    Bulto,
    DependenciaOF,
    Documento,
    IncidenciaDatos,
    LineaOF,
    Operacion,
    Operario,
    OrdenFabricacion,
    Recurso,
    Tanda,
    TrabajoProcesamiento,
)
from hidral_plan.modelos.enums import EstadoDocumento, EstadoOperacion, EstadoProgramacion, Severidad
from hidral_plan.planificacion import servicio as sv
from hidral_plan.planificacion.modelo import cargar_instantanea
from hidral_plan.servicios import ejecucion as ex

from .conftest import AHORA, plan_valido
from .generador_pdf import Aparato as ApGen
from .generador_pdf import OpcionesTanda, generar_tanda


def _deps(s) -> set[tuple[str, str]]:
    nums = dict(s.execute(select(OrdenFabricacion.id, OrdenFabricacion.numero)).all())
    return {(nums[o], nums[d]) for o, d in s.execute(select(DependenciaOF.of_origen_id, DependenciaOF.of_destino_id))}


def _tanda_con(n_aparatos: int, tmp_path, importar, **kw):
    aps = [ApGen(str(40001 + i)) for i in range(n_aparatos)]
    ruta = tmp_path / f"tanda_{n_aparatos}.pdf"
    esperado = generar_tanda(ruta, OpcionesTanda(aparatos=aps, **kw))
    r = importar(ruta)
    return r, esperado


@pytest.mark.parametrize("n", [1, 2, 4], ids=["A-1-aparato", "B-2-aparatos", "C-4-aparatos"])
def test_casos_A_B_C_tanda_con_n_aparatos(fabrica, importar, n):
    r, esperado = _tanda_con(n, fabrica, importar)
    with sesion() as s:
        d = s.get(Documento, r.documento_id)
        assert d.estado in (EstadoDocumento.COMPLETADO, EstadoDocumento.COMPLETADO_CON_ERRORES)
        tanda = s.scalar(select(Tanda))
        # la tanda NO tiene un número fijo de aparatos: exactamente los del documento
        assert {a.numero_control for a in tanda.aparatos} == esperado["aparatos"]
        ofs = {o.numero for o in s.scalars(select(OrdenFabricacion).where(OrdenFabricacion.tiene_hoja.is_(True)))}
        assert ofs == esperado["ofs"]
        stubs = {o.numero for o in s.scalars(select(OrdenFabricacion).where(OrdenFabricacion.tiene_hoja.is_(False)))}
        assert stubs == esperado["stubs"]
        assert esperado["dependencias"] <= _deps(s)
        assert s.scalar(select(func.count(Bulto.id))) == 3 * n
        assert s.scalar(select(func.count(IncidenciaDatos.id)).where(IncidenciaDatos.severidad == Severidad.CRITICA)) == 0
        # cada aparato conserva su semana (S40 + año de la emisión)
        assert {a.semana_codigo for a in tanda.aparatos} == {"202640"}
        res = sv.generar_plan(s, "test", AHORA)
    with sesion() as s:
        plan = sv.plan_activo(s)
        asigs = sv.asignaciones_de(s, plan)
        assert not plan_valido(asigs.values())
        # precedencias respetadas en el plan
        inst = cargar_instantanea(s, AHORA, incluir_bloqueadas_plan=False)
        for a in asigs.values():
            for p in inst.ops[a.op_id].predecesoras:
                if p in asigs:
                    assert asigs[p].fin <= a.inicio
        assert res["kpis"]["planificadas"] > 0
        assert len(res["riesgo_tandas"]) == 1


def test_caso_D_tanda_de_600_paginas_por_bloques(fabrica, importar):
    aps = [ApGen(str(50000 + i), ofs_relleno=12) for i in range(30)]
    ruta = fabrica / "grande.pdf"
    esperado = generar_tanda(ruta, OpcionesTanda(tanda="9600", aparatos=aps))
    assert esperado["paginas"] == 600
    tracemalloc.start()
    t0 = datetime.now()
    r = importar(ruta)
    _, pico = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    duracion = (datetime.now() - t0).total_seconds()
    with sesion() as s:
        t = s.scalar(select(TrabajoProcesamiento).where(TrabajoProcesamiento.documento_id == r.documento_id))
        assert t.paginas_procesadas == 600
        assert t.bloque_actual > 5, "debe procesarse en varios bloques, no de una vez"
        assert len({o.numero for o in s.scalars(select(OrdenFabricacion).where(OrdenFabricacion.tiene_hoja.is_(True)))}) == len(esperado["ofs"])
        assert s.scalar(select(func.count(Aparato.id))) == 30
    # memoria de Python acotada: no se retiene el documento completo
    assert pico < 200 * 1024 * 1024, f"pico de memoria {pico / 1e6:.0f} MB"
    assert duracion < 180


def test_caso_E_dos_tandas_con_recursos_compartidos(fabrica, importar):
    r1 = importar(fabrica / "x.pdf" if False else _gen(fabrica, "7001", 800000, ["60001", "60002"]))
    r2 = importar(_gen(fabrica, "7002", 810000, ["61001"]))
    assert not r1.duplicado and not r2.duplicado
    with sesion() as s:
        assert s.scalar(select(func.count(Tanda.id))) == 2
        sv.generar_plan(s, "test", AHORA)
    with sesion() as s:
        plan = sv.plan_activo(s)
        asigs = list(sv.asignaciones_de(s, plan).values())
        assert not plan_valido(asigs), "dos tandas comparten recursos sin solapes"
        tandas_por_recurso: dict[int, set] = {}
        for a in asigs:
            tandas_por_recurso.setdefault(a.recurso_id, set()).add(s.get(OrdenFabricacion, a.of_id).tanda_id)
        assert any(len(v) == 2 for v in tandas_por_recurso.values()), "algún recurso trabaja para ambas tandas"
        assert len(plan.riesgos["tandas"]) == 2


def _gen(tmp, tanda: str, base: int, controles: list[str], **kw):
    ruta = tmp / f"t{tanda}.pdf"
    generar_tanda(ruta, OpcionesTanda(tanda=tanda, base_of=base, aparatos=[ApGen(c) for c in controles], **kw))
    return ruta


def _plan_basico(fabrica, importar, **kw):
    importar(_gen(fabrica, "7100", 820000, ["62001", "62002"], **kw))
    with sesion() as s:
        sv.generar_plan(s, "test", AHORA)


def test_caso_F_maquina_averiada_replanifica_solo_la_zona_afectada(fabrica, importar):
    _plan_basico(fabrica, importar)
    with sesion() as s:
        lt = s.scalar(select(Recurso).where(Recurso.codigo == "LASERTUB"))
        antes = sv.asignaciones_de(s, sv.plan_activo(s))
        en_lt = [a for a in antes.values() if a.recurso_id == lt.id]
        assert en_lt
        ini = min(a.inicio for a in en_lt)
        r = sv.registrar_incidencia(s, {"tipo": "AVERIA", "recurso_id": lt.id, "inicio": ini.isoformat(), "horas": 6, "descripcion": "Avería LaserTub"}, "jefe", AHORA)
    assert r["replanificado"] and r["cambios"]
    with sesion() as s:
        despues = sv.asignaciones_de(s, sv.plan_activo(s))
        fin_averia = ini + timedelta(hours=6)
        for a in despues.values():
            if a.recurso_id == lt.id:
                assert all(t1 <= ini or t0 >= fin_averia for t0, t1 in a.tramos), "nada en la máquina durante la avería"
        cambiadas = {c["operacion_id"] for c in r["cambios"]}
        # solo cambia la zona afectada: las operaciones de la máquina y sus sucesoras
        assert cambiadas and len(cambiadas) < len(antes)
        assert not plan_valido(despues.values())
        assert all(c["motivo"].startswith("Avería LaserTub") for c in r["cambios"])
        assert r["tandas"][0]["riesgo_antes"] is not None
        assert s.get(Recurso, lt.id).estado == "AVERIADO"


def test_caso_G_trabajador_ausente(fabrica, importar):
    _plan_basico(fabrica, importar)
    with sesion() as s:
        antes = sv.asignaciones_de(s, sv.plan_activo(s))
        oid = next(a.operario_id for a in sorted(antes.values(), key=lambda a: a.inicio) if a.operario_id)
        r = sv.registrar_incidencia(s, {"tipo": "AUSENCIA", "operario_id": oid, "inicio": AHORA.isoformat(), "horas": 48, "descripcion": "Baja"}, "jefe", AHORA)
    assert r["replanificado"]
    with sesion() as s:
        despues = sv.asignaciones_de(s, sv.plan_activo(s))
        for a in despues.values():
            if a.operario_id == oid:
                assert a.inicio >= AHORA + timedelta(hours=48)
        # los trabajos se reasignan a otro operario cualificado o se desplazan, nunca a alguien no cualificado
        inst = cargar_instantanea(s, AHORA, incluir_bloqueadas_plan=False)
        for a in despues.values():
            if a.operario_id is not None:
                assert inst.operarios[a.operario_id].cualificado(inst.recursos[a.recurso_id], inst.ops[a.op_id])


def test_caso_H_falta_de_material(fabrica, importar):
    _plan_basico(fabrica, importar)
    with sesion() as s:
        of = s.scalar(select(OrdenFabricacion).where(OrdenFabricacion.grupo_hf == "SOLDADURA ESTRIBO"))
        r = sv.registrar_incidencia(s, {"tipo": "FALTA_MATERIAL", "of_id": of.id, "descripcion": "Sin chapa"}, "jefe", AHORA)
        of_id = of.id
    with sesion() as s:
        plan = sv.plan_activo(s)
        ops = {o.id for o in s.scalars(select(Operacion).where(Operacion.of_id == of_id))}
        assert not ops & set(sv.asignaciones_de(s, plan)), "sin material ni fecha no se planifica"
        assert any(n["motivo"] == "ESPERANDO_MATERIAL" for n in plan.no_planificadas)
        # las sucesoras tampoco (no se supone que el material llegará)
        assert any(n["motivo"] == "PREDECESORA_NO_PLANIFICABLE" for n in plan.no_planificadas)
        assert s.get(OrdenFabricacion, of_id).estado == "ESPERANDO_MATERIAL"
    assert r["replanificado"]
    # con fecha de material: se planifica después de esa fecha
    with sesion() as s:
        llega = AHORA + timedelta(days=2)
        sv.registrar_incidencia(s, {"tipo": "FALTA_MATERIAL", "of_id": of_id, "material_desde": llega.isoformat(), "descripcion": "Chapa llega el miércoles"}, "jefe", AHORA)
        of = s.get(OrdenFabricacion, of_id)
        of.material_disponible = None
        sv.generar_plan(s, "test", AHORA)
    with sesion() as s:
        asigs = sv.asignaciones_de(s, sv.plan_activo(s))
        propias = [a for a in asigs.values() if a.of_id == of_id]
        assert propias and all(a.inicio >= llega for a in propias)


def test_caso_I_of_urgente_simular_rechazar_aceptar(fabrica, importar):
    _plan_basico(fabrica, importar)
    with sesion() as s:
        plan0 = sv.plan_activo(s)
        antes = sv.asignaciones_de(s, plan0)
        # la OF de montaje del último aparato, que en el plan va tarde
        of = max(s.scalars(select(OrdenFabricacion).where(OrdenFabricacion.grupo_hf == "MONTAJE GUIAS-ESTRIBO-CABEZAL")), key=lambda o: o.fecha_prevista_inicio or datetime.min)
        r = sv.simular_of_urgente(s, of.id, "jefe", AHORA, "Cliente adelanta")
        assert r["texto"].startswith("Introducir esta OF ahora provocaría")
        sim_id = r["simulacion_id"]
    with sesion() as s:
        # simular NO cambia el plan oficial
        assert sv.plan_activo(s).id == plan0.id
        assert sv.asignaciones_de(s, sv.plan_activo(s)).keys() == antes.keys()
        sv.decidir_simulacion(s, sim_id, False, "jefe", "no compensa")
    with sesion() as s:
        assert sv.plan_activo(s).id == plan0.id
        r2 = sv.simular_of_urgente(s, of.id, "jefe", AHORA, "Cliente adelanta")
    with sesion() as s:
        res = sv.decidir_simulacion(s, r2["simulacion_id"], True, "jefe", "ok")
        assert res["aceptada"]
        nuevo = sv.plan_activo(s)
        assert nuevo.id != plan0.id
        assert s.get(OrdenFabricacion, of.id).urgente
        assert not plan_valido(sv.asignaciones_de(s, nuevo).values())


def test_caso_J_operacion_pendiente_de_programacion(fabrica, importar):
    _plan_basico(fabrica, importar)
    with sesion() as s:
        lch = s.scalar(select(OrdenFabricacion).where(OrdenFabricacion.seccion_codigo == "LCH", OrdenFabricacion.tiene_hoja.is_(True)))
        assert lch.estado_programacion == EstadoProgramacion.PENDIENTE_PROGRAMACION
        ops = sorted(lch.operaciones, key=lambda o: o.secuencia)
        assert [o.tipo for o in ops] == ["PROGRAMACION", "CORTE_LASER"]
        assert ops[1].estado == EstadoOperacion.PENDIENTE_PROGRAMACION
        asigs = sv.asignaciones_de(s, sv.plan_activo(s))
        assert asigs[ops[1].id].provisional and asigs[ops[1].id].inicio >= asigs[ops[0].id].fin
        # no se puede iniciar en máquina sin programa, aunque se intente forzar
        op17 = s.scalar(select(Operario).where(Operario.codigo_empleado == "OP17"))
        with pytest.raises(ex.FichajeRechazado) as e:
            ex.iniciar(s, op17.id, ops[1].id, "op17", AHORA, autorizado_por="jefe")
        assert any("programación" in m for m in e.value.errores)
        sv.registrar_programa(s, lch.id, "NEST-0001", "programador")
        assert lch.estado_programacion == EstadoProgramacion.LISTA_PARA_FABRICAR
        assert ops[0].estado == EstadoOperacion.TERMINADA and ops[1].estado == EstadoOperacion.LISTA
        f = ex.iniciar(s, op17.id, ops[1].id, "op17", AHORA)
        assert f["estado"] == "EN_CURSO"


def test_caso_K_lch(fabrica, importar):
    _plan_basico(fabrica, importar)
    with sesion() as s:
        lch = s.scalar(select(OrdenFabricacion).where(OrdenFabricacion.seccion_codigo == "LCH", OrdenFabricacion.tiene_hoja.is_(True)))
        piezas = list(s.scalars(select(LineaOF).where(LineaOF.of_id == lch.id)))
        assert {p.tipo for p in piezas} == {"PIEZA_CHAPA"}
        p = next(p for p in piezas if p.orden_plegado)
        assert (p.material, p.espesor_mm, p.largo_mm, p.ancho_mm) == ("DC01", 1.5, 119.0, 983.0)
        assert p.posicion == "1002" and p.cantidad == 4 and p.seccion_ref == "EH"
        pleg = s.scalar(select(OrdenFabricacion).where(OrdenFabricacion.numero == p.orden_plegado))
        assert pleg is not None and not pleg.tiene_hoja and pleg.operaciones[0].tipo == "PLEGADO"
        deps = _deps(s)
        assert (lch.numero, pleg.numero) in deps and (pleg.numero, p.orden_ref) in deps
        assert lch.semana_codigo == "202640"


def test_caso_L_lasertub(fabrica, importar):
    _plan_basico(fabrica, importar)
    with sesion() as s:
        cor = s.scalar(select(OrdenFabricacion).where(OrdenFabricacion.seccion_codigo == "COR"))
        assert cor.programa_codigo == "PL025286/A" and "LASERTUB" in cor.programa_descripcion
        assert cor.estado_programacion == EstadoProgramacion.PROGRAMADA
        op = cor.operaciones[0]
        assert op.tipo == "CORTE_TALADRO" and op.recurso_preferido == "LASERTUB"
        a = sv.asignaciones_de(s, sv.plan_activo(s))[op.id]
        assert s.get(Recurso, a.recurso_id).codigo == "LASERTUB"
        assert "programa" in a.explicacion["recurso"]["motivo"]


def test_caso_M_of_con_dependencia_pendiente(fabrica, importar):
    _plan_basico(fabrica, importar)
    with sesion() as s:
        mont = s.scalar(select(OrdenFabricacion).where(OrdenFabricacion.grupo_hf == "MONTAJE GUIAS-ESTRIBO-CABEZAL"))
        op = mont.operaciones[0]
        op01 = s.scalar(select(Operario).where(Operario.codigo_empleado == "OP01"))
        with pytest.raises(ex.FichajeRechazado) as e:
            ex.iniciar(s, op01.id, op.id, "op01", AHORA)
        assert any("predecesora" in m for m in e.value.errores)
        # un supervisor puede autorizar la excepción; queda registrada
        f = ex.iniciar(s, op01.id, op.id, "jefe", AHORA, autorizado_por="jefe")
        assert f["estado"] == "EN_CURSO"


def test_caso_N_datos_ambiguos(fabrica, importar):
    importar(_gen(fabrica, "7200", 830000, ["63001"], fila_sin_cantidad=True, control_ambiguo=True, seccion_desconocida=True, of_duplicada=True))
    with sesion() as s:
        tipos = {i.tipo: i for i in s.scalars(select(IncidenciaDatos))}
        assert "CANTIDAD_AUSENTE" in tipos, "cantidad ausente: se marca, no se inventa"
        assert "RELACION_AMBIGUA" in tipos and len(tipos["RELACION_AMBIGUA"].alternativas) == 2
        assert "SECCION_DESCONOCIDA" in tipos
        assert tipos["OF_DUPLICADA"].severidad == Severidad.CRITICA
        linea = s.scalar(select(LineaOF).where(LineaOF.articulo_codigo == "3001000/4", LineaOF.tipo == "SALIDA"))
        assert linea.cantidad is None
        # con un error crítico de integridad no se permite un plan definitivo
        with pytest.raises(sv.PlanBloqueado):
            sv.generar_plan(s, "test", AHORA, definitivo=True)
        # pero sí uno provisional para trabajar mientras se revisa
        assert sv.generar_plan(s, "test", AHORA, definitivo=False)["plan_id"]


def test_caso_O_pdf_duplicado(fabrica, importar):
    ruta = _gen(fabrica, "7300", 840000, ["64001"])
    r1 = importar(ruta)
    r2 = importar(ruta, "otro_nombre.pdf")
    assert r2.duplicado and r2.documento_id == r1.documento_id
    with sesion() as s:
        assert s.scalar(select(func.count(Documento.id))) == 1
        assert s.scalar(select(func.count(TrabajoProcesamiento.id))) == 1


def test_caso_P_nueva_version_del_mismo_pdf(fabrica, importar):
    r1 = importar(_gen(fabrica, "7400", 850000, ["65001", "65002"]))
    with sesion() as s:
        n_ofs_v1 = s.scalar(select(func.count(OrdenFabricacion.id)).where(OrdenFabricacion.tiene_hoja.is_(True)))
        mont = s.scalar(select(OrdenFabricacion).where(OrdenFabricacion.grupo_hf == "MONTAJE GUIAS-ESTRIBO-CABEZAL"))
        mont_id, mont_num = mont.id, mont.numero
    ruta2 = fabrica / "t7400_v2.pdf"
    generar_tanda(ruta2, OpcionesTanda(tanda="7400", base_of=850000, aparatos=[ApGen("65001"), ApGen("65002")], omitir_embalaje_de="65002", cantidad_montaje=3))
    r2 = importar(ruta2)
    assert not r2.duplicado and r2.nueva_version and r2.version == 2
    with sesion() as s:
        assert s.get(Documento, r1.documento_id).estado == EstadoDocumento.SUSTITUIDO
        # mismas OF (sin duplicarlas), líneas sustituidas por las de la nueva versión
        mont = s.get(OrdenFabricacion, mont_id)
        assert mont.numero == mont_num and mont.documento_id == r2.documento_id
        salida = s.scalar(select(LineaOF).where(LineaOF.of_id == mont_id, LineaOF.tipo == "SALIDA"))
        assert salida.cantidad == 3
        assert s.scalar(select(func.count(LineaOF.id)).where(LineaOF.of_id == mont_id, LineaOF.tipo == "SALIDA")) == 1
        aus = s.scalar(select(IncidenciaDatos).where(IncidenciaDatos.tipo == "OF_AUSENTE_EN_NUEVA_VERSION"))
        assert aus is not None and len(aus.alternativas) == 1
        assert s.scalar(select(func.count(OrdenFabricacion.id)).where(OrdenFabricacion.tiene_hoja.is_(True))) == n_ofs_v1  # la ausente no se borra
        d2 = s.get(Documento, r2.documento_id)
        assert d2.resumen["cambios_version"]["ofs_ausentes"] == aus.alternativas


def test_dependencia_circular_es_critica(fabrica, importar):
    importar(_gen(fabrica, "7500", 860000, ["66001"], ciclo=True))
    with sesion() as s:
        ciclos = list(s.scalars(select(IncidenciaDatos).where(IncidenciaDatos.tipo == "DEPENDENCIA_CIRCULAR")))
        assert ciclos and ciclos[0].severidad == Severidad.CRITICA
        comprob = sv.comprobaciones_previas(s, cargar_instantanea(s, AHORA))
        assert any(c["estado"] == "BLOQUEANTE" for c in comprob)
        r = sv.generar_plan(s, "test", AHORA)
        assert r["no_planificadas"] > 0  # las OF del ciclo no se pueden ordenar


def test_procesamiento_asincrono_devuelve_inmediatamente(fabrica):
    from hidral_plan.ingesta.pipeline import registrar_documento

    ruta = _gen(fabrica, "7600", 870000, ["67001"])
    r = registrar_documento(ruta, "t.pdf", "test")
    with sesion() as s:
        t = s.get(TrabajoProcesamiento, r.trabajo_id)
        assert t.estado == "EN_COLA" and t.paginas_totales > 0 and t.paginas_procesadas == 0
    from hidral_plan.ingesta.cola import reclamar_trabajo
    from hidral_plan.ingesta.pipeline import procesar_trabajo

    tid = reclamar_trabajo("test")
    assert tid == r.trabajo_id
    procesar_trabajo(tid)
    with sesion() as s:
        assert s.get(TrabajoProcesamiento, tid).estado == "COMPLETADO"


_ = (AsignacionPlan, procesar_sincrono)
