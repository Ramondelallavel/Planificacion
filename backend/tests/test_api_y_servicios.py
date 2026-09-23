"""API, permisos, cambios manuales, integraciones, aprendizaje, explicabilidad y reanudación."""

from __future__ import annotations

import warnings
from datetime import timedelta

import pytest
from sqlalchemy import func, select

from hidral_plan.db import sesion
from hidral_plan.modelos import AsignacionPlan, Auditoria, EstimacionPropuesta, Fichaje, Operacion, OrdenFabricacion, Recurso, TrabajoProcesamiento
from hidral_plan.planificacion import servicio as sv

from .conftest import AHORA
from .generador_pdf import Aparato as ApGen
from .generador_pdf import OpcionesTanda, generar_tanda

warnings.filterwarnings("ignore", category=DeprecationWarning)


@pytest.fixture()
def cliente(fabrica):
    from fastapi.testclient import TestClient

    from hidral_plan.api.app import crear_app

    with TestClient(crear_app()) as c:
        yield c


def _login(c, usuario: str) -> dict:
    r = c.post("/api/auth/login", json={"usuario": usuario, "clave": "hidral"})
    assert r.status_code == 200
    return {"Authorization": f"Bearer {r.json()['token']}"}


def _pdf(tmp, **kw):
    ruta = tmp / "api.pdf"
    generar_tanda(ruta, OpcionesTanda(aparatos=[ApGen("70001"), ApGen("70002")], **kw))
    return ruta


def test_flujo_api_completo(cliente, fabrica):
    from hidral_plan.ingesta.cola import reclamar_trabajo
    from hidral_plan.ingesta.pipeline import procesar_trabajo

    h = _login(cliente, "planificador")
    assert cliente.get("/api/tandas").status_code == 401
    r = cliente.post("/api/documentos", headers=h, files={"fichero": ("t.pdf", _pdf(fabrica).read_bytes(), "application/pdf")})
    assert r.status_code == 202 and r.json()["estado"] == "En cola"
    procesar_trabajo(reclamar_trabajo("test"))
    t = cliente.get(f"/api/trabajos/{r.json()['trabajo_id']}", headers=h).json()
    assert t["estado"] == "COMPLETADO" and t["porcentaje"] == 100.0 and t["contadores"]["aparatos"] == 2
    assert cliente.post("/api/plan/generar", headers=h, json={}).status_code == 200
    ct = cliente.get("/api/dashboard/control-tower", headers=h).json()
    assert ct["plan"] and ct["alertas"] and "resumen" in ct
    gantt = cliente.get("/api/plan/activo/gantt", headers=h).json()
    assert gantt["asignaciones"] and gantt["turnos"]
    op_id = gantt["asignaciones"][0]["operacion_id"]
    ex = cliente.get(f"/api/plan/asignaciones/{op_id}", headers=h).json()["explicacion"]
    # explicabilidad: no solo un número, también los motivos
    assert ex["prioridad"]["motivos"] and ex["recurso"]["motivo"] and ex["inicio_condicionado_por"]
    # un cambio imposible se rechaza con 409 y los motivos, y queda auditado
    sabado = (AHORA + timedelta(days=5)).replace(hour=10).isoformat()
    r = cliente.post(f"/api/plan/asignaciones/{op_id}/mover", headers=h, json={"inicio": sabado, "motivo": "prueba"})
    assert r.status_code == 409 and r.json()["errores"]
    assert cliente.get("/api/auditoria?accion=CAMBIO_MANUAL_RECHAZADO", headers=h).json()
    assert cliente.get("/api/dashboard/global", headers=h).status_code == 200
    assert cliente.get("/api/plan/activo/turnos", headers=h).json()["turnos"]


def test_permisos_por_rol(cliente, fabrica):
    consulta = _login(cliente, "consulta")
    op = _login(cliente, "op01")
    assert cliente.post("/api/plan/generar", headers=consulta, json={}).status_code == 403
    assert cliente.post("/api/plan/generar", headers=op, json={}).status_code == 403
    assert cliente.get("/api/tandas", headers=consulta).status_code == 200
    assert cliente.get("/api/operario/trabajo", headers=op).status_code == 200
    assert cliente.get("/api/operario/trabajo?operario_id=2", headers=op).status_code == 403
    assert cliente.put("/api/configuracion/pesos_prioridad", headers=_login(cliente, "jefe"), json={"valor": {"holgura": 1}}).status_code == 403


def test_movimiento_manual_valido_propaga_sucesoras(fabrica, importar):
    importar(_pdf(fabrica))
    with sesion() as s:
        sv.generar_plan(s, "test", AHORA)
    with sesion() as s:
        plan = sv.plan_activo(s)
        pint = s.scalar(select(OrdenFabricacion).where(OrdenFabricacion.grupo_hf == "PINTURA POLVO PINO"))
        a = s.scalar(select(AsignacionPlan).where(AsignacionPlan.plan_id == plan.id, AsignacionPlan.of_id == pint.id))
        nuevo = (a.inicio + timedelta(days=1)).replace(hour=8, minute=0)
        r = sv.mover_asignacion(s, a.operacion_id, "jefe", AHORA, inicio=nuevo, motivo="Retraso de pintura", bloquear=True)
        assert r["aceptado"]
    with sesion() as s:
        asigs = sv.asignaciones_de(s, sv.plan_activo(s))
        assert asigs[a.operacion_id].inicio == nuevo
        assert s.scalar(select(AsignacionPlan).where(AsignacionPlan.operacion_id == a.operacion_id)).bloqueada
        from hidral_plan.planificacion.modelo import cargar_instantanea

        inst = cargar_instantanea(s, AHORA, incluir_bloqueadas_plan=False)
        for suc in inst.sucesoras_op(a.operacion_id):
            if suc in asigs:
                assert asigs[suc].inicio >= asigs[a.operacion_id].fin
        assert s.scalar(select(func.count(Auditoria.id)).where(Auditoria.accion == "CAMBIO_MANUAL_PLAN")) == 1
    # la asignación bloqueada se respeta al regenerar el plan
    with sesion() as s:
        sv.generar_plan(s, "test", AHORA)
    with sesion() as s:
        assert sv.asignaciones_de(s, sv.plan_activo(s))[a.operacion_id].inicio == nuevo


def test_integraciones_csv(fabrica, importar):
    from hidral_plan.integraciones.adaptadores import AdaptadorCSV, importar_mrp, importar_ortems, importar_teamcenter

    importar(_pdf(fabrica))
    with sesion() as s:
        mont = s.scalar(select(OrdenFabricacion).where(OrdenFabricacion.grupo_hf == "MONTAJE GUIAS-ESTRIBO-CABEZAL"))
        r = importar_ortems(s, AdaptadorCSV("ORTEMS", f"of;prioridad;semana\n{mont.numero};90;202641\n999999;10;202640\n"), "test")
        assert r.actualizadas == 1 and r.sin_correspondencia and r.conflictos
        assert mont.prioridad_ortems == 90 and mont.semana_codigo == "202641"  # ORTEMS es maestro de fechas
        r = importar_mrp(s, AdaptadorCSV("MRP", f"of,material_disponible,fecha_material\n{mont.numero},N,2026-09-23 07:00\n"), "test")
        assert mont.material_disponible is False and mont.material_disponible_desde.day == 23
        r = importar_teamcenter(s, AdaptadorCSV("TC", "articulo;revision;descripcion;plano\n3001000;4;CONJ. GUIAS HO (TC);PL-3001000-4\n"), "test")
        assert r.actualizadas == 1


def test_aprendizaje_propone_y_requiere_aprobacion(fabrica, importar):
    from hidral_plan.servicios import ejecucion as ex

    importar(_pdf(fabrica))
    with sesion() as s:
        cfg = {"muestras_minimas": 2, "desviacion_minima": 0.1}
        from hidral_plan import configuracion

        configuracion.guardar(s, "aprendizaje", cfg, "test")
        ops = list(s.scalars(select(Operacion).where(Operacion.tipo == "SOLDADURA", Operacion.seccion_codigo == "EH")))
        te = ops[0].tiempo_estandar_id
        for op in ops:
            op.estado = "TERMINADA"
            op.duracion_real_min = op.duracion_estimada_min * 1.5
            s.add(Fichaje(operario_id=1, of_id=op.of_id, operacion_id=op.id, inicio=AHORA, fin=AHORA, estado="CERRADO", duracion_real_min=op.duracion_real_min))
        s.flush()
        props = ex.proponer_estimaciones(s)
        assert props and props[0]["tiempo_estandar_id"] == te and props[0]["ratio"] == 1.5
        # nada cambia hasta que un responsable lo aprueba
        from hidral_plan.modelos import TiempoEstandar

        assert s.get(TiempoEstandar, te).vigente
        r = ex.decidir_estimacion(s, props[0]["id"], True, "planificador")
        assert not s.get(TiempoEstandar, te).vigente and s.get(TiempoEstandar, r["tiempo_estandar_nuevo"]).fuente == "APRENDIZAJE"
        # reversible
        ex.revertir_tiempo_estandar(s, r["tiempo_estandar_nuevo"], "planificador")
        assert s.get(TiempoEstandar, te).vigente
        assert s.scalar(select(EstimacionPropuesta)).estado == "APROBADA"


def test_reanudacion_tras_caida(fabrica, monkeypatch):
    """Si el proceso muere a mitad, el trabajo se reanuda desde el último bloque sin duplicar datos."""
    from hidral_plan.config import reiniciar_ajustes
    from hidral_plan.ingesta import pipeline
    from hidral_plan.ingesta.cola import reclamar_trabajo
    from hidral_plan.modelos import LineaOF

    monkeypatch.setenv("HIDRAL_BLOQUE_MAX", "8")  # bloques pequeños para que haya varios
    reiniciar_ajustes()
    ruta = fabrica / "grande.pdf"
    generar_tanda(ruta, OpcionesTanda(aparatos=[ApGen(str(71000 + i), ofs_relleno=4) for i in range(4)]))
    r = pipeline.registrar_documento(ruta, "grande.pdf", "test")
    original = pipeline.persistir_bloque
    llamadas = {"n": 0}

    def fallo(*a, **k):
        llamadas["n"] += 1
        if llamadas["n"] == 3:
            raise RuntimeError("corte de luz simulado")
        return original(*a, **k)

    monkeypatch.setattr(pipeline, "persistir_bloque", fallo)
    pipeline.procesar_trabajo(reclamar_trabajo("w1"))
    with sesion() as s:
        t = s.get(TrabajoProcesamiento, r.trabajo_id)
        assert t.estado == "ERROR" and 0 < t.paginas_procesadas < t.paginas_totales
        hechas = t.paginas_procesadas
        # se reencola (en producción lo hace el latido caducado o un operador)
        t.estado = "EN_COLA"
    monkeypatch.setattr(pipeline, "persistir_bloque", original)
    pipeline.procesar_trabajo(reclamar_trabajo("w2"))
    with sesion() as s:
        t = s.get(TrabajoProcesamiento, r.trabajo_id)
        assert t.estado == "COMPLETADO" and t.paginas_procesadas == t.paginas_totales and hechas > 0
        # sin duplicados: cada OF de montaje tiene exactamente sus 3 líneas
        for of in s.scalars(select(OrdenFabricacion).where(OrdenFabricacion.grupo_hf == "MONTAJE GUIAS-ESTRIBO-CABEZAL")):
            assert s.scalar(select(func.count(LineaOF.id)).where(LineaOF.of_id == of.id)) == 3


def test_what_if_no_modifica_el_plan_real(fabrica, importar):
    importar(_pdf(fabrica))
    with sesion() as s:
        sv.generar_plan(s, "test", AHORA)
    with sesion() as s:
        plan = sv.plan_activo(s)
        antes = {k: (v.inicio, v.fin) for k, v in sv.asignaciones_de(s, plan).items()}
        lt = s.scalar(select(Recurso).where(Recurso.codigo == "LASERTUB"))
        r = sv.simular_escenario(s, {"averias": [{"recurso_id": lt.id, "horas": 16}], "faltan_operarios": [{"seccion": "MF", "cantidad": 1}]}, "jefe", AHORA)
        assert r["escenario"] and r["kpis_base"] and r["kpis_simulado"] and r["simulacion_id"]
    with sesion() as s:
        assert sv.plan_activo(s).id == plan.id
        assert {k: (v.inicio, v.fin) for k, v in sv.asignaciones_de(s, sv.plan_activo(s)).items()} == antes
        assert s.get(Recurso, lt.id).estado == "OPERATIVO"
