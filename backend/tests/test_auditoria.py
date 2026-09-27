"""Pruebas de la auditoría: zonas de la API que no cubrían las demás pruebas."""

from __future__ import annotations

import pytest

from .generador_pdf import Aparato as ApGen
from .generador_pdf import OpcionesTanda, generar_tanda


@pytest.fixture()
def cliente(fabrica):
    from fastapi.testclient import TestClient

    from hidral_plan.api.app import crear_app

    with TestClient(crear_app()) as c:
        yield c


def _login(c, usuario: str = "planificador") -> dict:
    r = c.post("/api/auth/login", json={"usuario": usuario, "clave": "hidral"})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}


@pytest.fixture()
def con_plan(cliente, fabrica):
    from hidral_plan.ingesta.cola import reclamar_trabajo
    from hidral_plan.ingesta.pipeline import procesar_trabajo

    h = _login(cliente)
    ruta = fabrica / "t.pdf"
    generar_tanda(ruta, OpcionesTanda(aparatos=[ApGen("70001"), ApGen("70002")]))
    cliente.post("/api/documentos", headers=h, files={"fichero": ("t.pdf", ruta.read_bytes(), "application/pdf")})
    procesar_trabajo(reclamar_trabajo("test"))
    assert cliente.post("/api/plan/generar", headers=h, json={}).status_code == 200
    return h


def test_incidencias_de_produccion_por_api(cliente, con_plan):
    h = con_plan
    gantt = cliente.get("/api/plan/activo/gantt", headers=h).json()["asignaciones"]
    rec = next(r for r in cliente.get("/api/recursos", headers=h).json() if r["codigo"] == gantt[0]["recurso"])
    r = cliente.post("/api/incidencias", headers=h, json={"tipo": "AVERIA", "descripcion": "rodamiento", "recurso_id": rec["id"], "horas": 4})
    assert r.status_code == 200, r.text
    inc = r.json()
    assert inc["incidencia_id"]
    lista = cliente.get("/api/incidencias?estado=ABIERTA", headers=h).json()
    assert any(i["id"] == inc["incidencia_id"] for i in lista)
    assert any("AVERIA" in a["titulo"] for a in cliente.get("/api/notificaciones?solo_roles=true", headers=_login(cliente, "jefe")).json())
    assert cliente.post(f"/api/incidencias/{inc['incidencia_id']}/cerrar", headers=h).status_code == 200
    assert next(r for r in cliente.get("/api/recursos", headers=h).json() if r["id"] == rec["id"])["estado"] == "OPERATIVO"
    # otros tipos
    ops = cliente.get("/api/operarios", headers=h).json()
    for cuerpo in (
        {"tipo": "AUSENCIA", "descripcion": "médico", "operario_id": ops[0]["id"], "horas": 3},
        {"tipo": "FALTA_MATERIAL", "descripcion": "sin chapa", "of_id": gantt[0]["of_id"]},
        {"tipo": "RETRASO", "descripcion": "va lenta", "operacion_id": gantt[0]["operacion_id"], "minutos_extra": 30},
    ):
        r = cliente.post("/api/incidencias", headers=h, json=cuerpo)
        assert r.status_code in (200, 400), (cuerpo, r.text)
    assert cliente.post("/api/incidencias", headers=_login(cliente, "op01"), json={"tipo": "AVERIA", "descripcion": "x"}).status_code in (403, 400)


def test_incidencia_desde_pantalla_de_operario(cliente, con_plan):
    ho = _login(cliente, "op01")
    t = cliente.get("/api/operario/trabajo", headers=ho).json()
    r = cliente.post("/api/operario/incidencia", headers=ho, json={"operacion_id": t["siguiente"]["operacion_id"], "tipo": "CALIDAD", "descripcion": "rebaba"})
    assert r.status_code == 200, r.text


def test_fichajes_pausa_reanudar_parcial_y_ajenos(cliente, con_plan):
    ho, hj = _login(cliente, "op01"), _login(cliente, "jefe")
    t = cliente.get("/api/operario/trabajo", headers=ho).json()
    r = cliente.post("/api/operario/iniciar", headers=hj, json={"operacion_id": t["siguiente"]["operacion_id"], "operario_id": t["operario"]["id"], "autorizado_por": "jefe"})
    assert r.status_code == 200, r.text
    fid = cliente.get("/api/operario/trabajo", headers=ho).json()["actual"]["fichaje_id"]
    otro = _login(cliente, "op13")
    assert cliente.post(f"/api/operario/fichajes/{fid}/pausar", headers=otro, json={}).status_code == 403
    assert cliente.post(f"/api/operario/fichajes/{fid}/pausar", headers=ho, json={"motivo": "café"}).status_code == 200
    assert cliente.post(f"/api/operario/fichajes/{fid}/reanudar", headers=ho).status_code == 200
    r = cliente.post(f"/api/operario/fichajes/{fid}/terminar", headers=ho, json={"parcial": True, "cantidad": 0})
    assert r.status_code in (200, 409), r.text


@pytest.mark.parametrize(
    "escenario",
    [
        {"ausencias": [{"operario_id": 1, "horas": 8}]},
        {"faltan_operarios": [{"seccion": "LCH", "cantidad": 1}]},
        {"falta_material": [{"of_id": None}]},
        {"retrasos": [{"operacion_id": None, "minutos": 60}]},
        {"recursos_extra": [{"clonar_recurso_id": None, "cantidad": 1}]},
        {"pesos_prioridad": {"holgura": 0.9}},
        {"adelantar_of": [None]},
        {"modo": "incremental", "averias": [{"recurso_id": None, "horas": 2}]},
    ],
)
def test_escenarios_what_if(cliente, con_plan, escenario):
    h = con_plan
    gantt = cliente.get("/api/plan/activo/gantt", headers=h).json()["asignaciones"]
    a = gantt[0]
    # completar los ids con datos reales
    for clave, lista in escenario.items():
        if isinstance(lista, list):
            for x in lista:
                if isinstance(x, dict):
                    for k in ("of_id", "operacion_id", "clonar_recurso_id", "recurso_id"):
                        if k in x and x[k] is None:
                            x[k] = a["recurso_id"] if k in ("clonar_recurso_id", "recurso_id") else a[k]
            escenario[clave] = [a["of_id"] if x is None else x for x in lista]
    r = cliente.post("/api/plan/simulaciones/escenario", headers=h, json={"escenario": escenario, "guardar": False})
    assert r.status_code == 200, r.text
    assert r.json()["kpis_simulado"]["operaciones"] > 0


def test_of_urgente_simular_y_decidir(cliente, con_plan):
    h = con_plan
    of = cliente.get("/api/ofs?limite=50", headers=h).json()["items"][-1]
    r = cliente.post("/api/plan/simulaciones/of-urgente", headers=h, json={"of_id": of["id"], "motivo": "cliente"})
    assert r.status_code == 200, r.text
    sim = r.json()["simulacion_id"]
    assert cliente.post(f"/api/plan/simulaciones/{sim}/decidir", headers=h, json={"aceptar": False, "motivo": "no"}).status_code == 200
    r = cliente.post("/api/plan/simulaciones/of-urgente", headers=h, json={"of_id": of["id"]}).json()
    assert cliente.post(f"/api/plan/simulaciones/{r['simulacion_id']}/decidir", headers=h, json={"aceptar": True, "motivo": "sí"}).status_code == 200
    assert cliente.get(f"/api/ofs/{of['id']}", headers=h).json()["urgente"] is True


def test_mover_y_bloquear_asignacion(cliente, con_plan):
    h = con_plan
    a = cliente.get("/api/plan/activo/gantt", headers=h).json()["asignaciones"][0]
    r = cliente.post(f"/api/plan/asignaciones/{a['operacion_id']}/bloquear", headers=h, json={"bloqueada": True, "motivo": "no tocar"})
    assert r.status_code == 200, r.text
    assert cliente.get(f"/api/plan/asignaciones/{a['operacion_id']}", headers=h).status_code == 200
    r = cliente.post(f"/api/plan/asignaciones/{a['operacion_id']}/mover", headers=h, json={"inicio": "2026-09-27T03:00:00", "motivo": "domingo de madrugada"})
    assert r.status_code == 409
    assert cliente.get("/api/plan/historico", headers=h).status_code == 200
    assert cliente.get("/api/plan/activo/cambios", headers=h).status_code == 200
    assert cliente.get("/api/plan/activo/turnos?dia=2026-09-21", headers=h).status_code == 200


def test_documento_paginas_incidencias_y_trazabilidad(cliente, con_plan):
    h = con_plan
    doc = cliente.get("/api/documentos", headers=h).json()[0]
    assert cliente.get(f"/api/documentos/{doc['id']}/paginas", headers=h).json()
    assert cliente.get(f"/api/documentos/{doc['id']}/paginas/1", headers=h).status_code == 200
    img = cliente.get(f"/api/documentos/{doc['id']}/paginas/1/imagen", headers=h)
    assert img.status_code == 200 and img.headers["content-type"] == "image/png"
    assert cliente.get(f"/api/documentos/{doc['id']}/paginas/999", headers=h).status_code == 404
    incs = cliente.get(f"/api/documentos/{doc['id']}/incidencias?estado=ABIERTA", headers=h).json()
    if incs:
        assert cliente.patch(f"/api/incidencias-datos/{incs[0]['id']}", headers=h, json={"estado": "REVISADA", "resolucion": "ok"}).status_code == 200
        assert cliente.patch(f"/api/incidencias-datos/{incs[0]['id']}", headers=h, json={"estado": "INVENTADO"}).status_code == 400
    of = cliente.get(f"/api/documentos/{doc['id']}/ofs", headers=h).json()
    assert of
    assert cliente.get(f"/api/trazabilidad/OF/{of[0]['id'] if isinstance(of, list) else 1}", headers=h).status_code == 200
    assert cliente.get("/api/trazabilidad/INVENTADO/1", headers=h).status_code in (200, 400, 404)


def test_configuracion_turnos_secciones_tiempos_y_parametros(cliente, con_plan):
    h = con_plan
    assert cliente.put("/api/turnos/X", headers=h, json={"codigo": "X", "nombre": "Extra", "hora_inicio": "25:99", "hora_fin": "30:00"}).status_code == 400
    assert cliente.put("/api/turnos/X", headers=h, json={"codigo": "X", "nombre": "Extra", "hora_inicio": "06:00", "hora_fin": "14:00", "dias_semana": [9]}).status_code == 400
    assert cliente.put("/api/turnos/X", headers=h, json={"codigo": "X", "nombre": "Sábados", "hora_inicio": "06:00", "hora_fin": "14:00", "dias_semana": [5]}).status_code == 200
    assert cliente.patch("/api/secciones/LCH", headers=h, json={"nombre": "Láser chapa"}).status_code == 200
    assert cliente.patch("/api/secciones/NOEXISTE", headers=h, json={"nombre": "x"}).status_code == 404
    assert cliente.post("/api/tiempos-estandar", headers=h, json={"seccion": "LCH", "tipo_operacion": "CORTE_LASER", "minutos_preparacion": 10, "minutos_por_unidad": 2}).status_code == 200
    assert cliente.put("/api/configuracion/inexistente", headers=h, json={"valor": {}}).status_code == 404
    assert cliente.put("/api/configuracion/pesos_prioridad", headers=h, json={"valor": {"holgura": "mucho"}}).status_code == 400
    assert cliente.put("/api/configuracion/planificacion", headers=h, json={"valor": {"horizonte_dias": -3}}).status_code == 400
    assert cliente.put("/api/configuracion/pesos_prioridad", headers=h, json={"valor": {"holgura": 0.5}, "motivo": "prueba"}).status_code == 200
    ops = cliente.get("/api/operarios", headers=h).json()
    assert cliente.post(f"/api/operarios/{ops[0]['id']}/ausencias", headers=h, json={"inicio": "2026-09-22T06:00", "fin": "2026-09-22T14:00", "motivo": "médico"}).status_code == 200
    assert cliente.post(f"/api/operarios/{ops[0]['id']}/ausencias", headers=h, json={"inicio": "2026-09-22T14:00", "fin": "2026-09-22T06:00", "motivo": "al revés"}).status_code == 400
    # el plan se sigue generando con todo lo anterior
    assert cliente.post("/api/plan/generar", headers=h, json={}).status_code == 200


def test_usuario_de_consulta_no_cambia_nada(cliente, con_plan):
    from hidral_plan.db import sesion
    from hidral_plan.modelos import Usuario
    from hidral_plan.seguridad import hash_clave

    with sesion() as s:
        s.add(Usuario(usuario="lector", nombre="Lector", rol="CONSULTA", hash_clave=hash_clave("hidral"), activo=True))
    hc = _login(cliente, "lector")
    assert cliente.get("/api/dashboard/control-tower", headers=hc).status_code == 200
    assert cliente.post("/api/operario/incidencia", headers=hc, json={"tipo": "AVERIA", "descripcion": "x"}).status_code == 403
    assert cliente.post("/api/plan/generar", headers=hc, json={}).status_code == 403


# ------------------------------------------------------------------ seguridad
def test_bloqueo_tras_intentos_fallidos(cliente, fabrica):
    for _ in range(5):
        assert cliente.post("/api/auth/login", json={"usuario": "jefe", "clave": "mala"}).status_code == 401
    r = cliente.post("/api/auth/login", json={"usuario": "jefe", "clave": "hidral"})
    assert r.status_code == 429 and "Demasiados intentos" in r.json()["detail"]
    # otro usuario no se ve afectado
    assert cliente.post("/api/auth/login", json={"usuario": "planificador", "clave": "hidral"}).status_code == 200


def test_usuario_dado_de_baja_o_con_otro_rol_al_momento(cliente, fabrica):
    ha = _login(cliente, "admin")
    hs = _login(cliente, "supervisor")
    assert cliente.get("/api/tandas", headers=hs).status_code == 200
    assert cliente.patch("/api/usuarios/supervisor", headers=ha, json={"rol": "OPERARIO"}).status_code == 200
    assert cliente.get("/api/tandas", headers=hs).status_code == 403  # el mismo token, rol nuevo
    assert cliente.patch("/api/usuarios/supervisor", headers=ha, json={"activo": False}).status_code == 200
    assert cliente.get("/api/auth/yo", headers=hs).status_code == 401


def test_cambio_de_clave_y_gestion_de_usuarios(cliente, fabrica):
    ha = _login(cliente, "admin")
    hp = _login(cliente)
    assert cliente.get("/api/usuarios", headers=hp).status_code == 403
    assert cliente.post("/api/usuarios", headers=ha, json={"usuario": "Nuevo", "nombre": "Nuevo", "rol": "INVENTADO", "clave": "12345678"}).status_code == 400
    assert cliente.post("/api/usuarios", headers=ha, json={"usuario": "Nuevo", "nombre": "Nuevo", "rol": "CONSULTA", "clave": "corta"}).status_code == 400
    r = cliente.post("/api/usuarios", headers=ha, json={"usuario": "Nuevo", "nombre": "Nuevo", "rol": "CONSULTA", "clave": "12345678"})
    assert r.status_code == 200 and r.json()["usuario"] == "nuevo"
    assert cliente.post("/api/usuarios", headers=ha, json={"usuario": "nuevo", "nombre": "x", "rol": "CONSULTA", "clave": "12345678"}).status_code == 409
    hn = cliente.post("/api/auth/login", json={"usuario": "nuevo", "clave": "12345678"}).json()
    hn = {"Authorization": f"Bearer {hn['token']}"}
    assert cliente.post("/api/auth/clave", headers=hn, json={"actual": "mal", "nueva": "otra-clave-1"}).status_code == 400
    assert cliente.post("/api/auth/clave", headers=hn, json={"actual": "12345678", "nueva": "otra-clave-1"}).status_code == 200
    assert cliente.post("/api/auth/login", json={"usuario": "nuevo", "clave": "otra-clave-1"}).status_code == 200
    # último administrador y baja propia
    assert cliente.patch("/api/usuarios/admin", headers=ha, json={"rol": "CONSULTA"}).status_code == 409
    assert cliente.patch("/api/usuarios/admin", headers=ha, json={"activo": False}).status_code == 409
    assert cliente.patch("/api/usuarios/noexiste", headers=ha, json={"nombre": "x"}).status_code == 404


def test_secreto_aleatorio_persistente(tmp_path, monkeypatch):
    from hidral_plan.config import _secreto

    monkeypatch.delenv("HIDRAL_SECRETO", raising=False)
    monkeypatch.setenv("HIDRAL_ALMACEN_DIR", str(tmp_path / "datos" / "almacen"))
    a = _secreto()
    assert len(a) == 64 and a != "cambiar-en-produccion"
    assert _secreto() == a  # se conserva entre arranques
    monkeypatch.setenv("HIDRAL_SECRETO", "definido-por-entorno")
    assert _secreto() == "definido-por-entorno"


def test_avisos_por_rol_y_no_se_marcan_los_ajenos(cliente, con_plan):
    from hidral_plan.db import sesion
    from hidral_plan.modelos import Notificacion

    with sesion() as s:
        s.add(Notificacion(rol_destino="PLANIFICADOR", titulo="solo planificación", mensaje="x", nivel="AVISO"))
        s.add(Notificacion(rol_destino="MANDOS", titulo="para mandos", mensaje="x", nivel="AVISO"))
    hj = _login(cliente, "jefe")
    titulos = {a["titulo"] for a in cliente.get("/api/notificaciones?solo_roles=true", headers=hj).json()}
    assert "para mandos" in titulos and "solo planificación" not in titulos
    propia = next(a for a in cliente.get("/api/notificaciones?solo_roles=true", headers=con_plan).json() if a["titulo"] == "solo planificación")
    assert cliente.post(f"/api/notificaciones/{propia['id']}/leida", headers=_login(cliente, "op01")).status_code == 404
    assert cliente.post(f"/api/notificaciones/{propia['id']}/leida", headers=con_plan).status_code == 200


def test_limite_de_tamano_de_subida(cliente, fabrica, monkeypatch):
    from hidral_plan.config import ajustes

    monkeypatch.setattr(ajustes(), "max_pdf_mb", 0)
    h = _login(cliente)
    r = cliente.post("/api/documentos", headers=h, files={"fichero": ("t.pdf", b"%PDF-1.4 " + b"x" * 2048, "application/pdf")})
    assert r.status_code == 413
    monkeypatch.setattr(ajustes(), "max_pdf_mb", 300)
    assert cliente.post("/api/documentos", headers=h, files={"fichero": ("vacio.pdf", b"", "application/pdf")}).status_code == 400


# ------------------------------------------------------------------ datos
def test_numeros_espanoles_e_ingleses():
    from hidral_plan.api.rutas.materiales import numero_es

    assert [numero_es(x) for x in ("1.234,5", "1234,5", "1.234", "1234.5", "1,234.5", "20", " 3 ")] == [1234.5, 1234.5, 1234, 1234.5, 1234.5, 20, 3]
    with pytest.raises(ValueError):
        numero_es("-3")
    with pytest.raises(ValueError):
        numero_es("abc")


def test_migracion_de_columnas_nuevas(entorno):
    from sqlalchemy import inspect, text

    from hidral_plan.db import Base, crear_tablas, motor

    crear_tablas()
    with motor().begin() as con:  # una tabla «de la versión anterior», sin columnas nuevas
        con.execute(text("DROP TABLE entrada_material"))
        con.execute(text("DROP TABLE material"))
        con.execute(text("CREATE TABLE material (codigo VARCHAR(40) PRIMARY KEY, stock FLOAT)"))
        con.execute(text("INSERT INTO material (codigo, stock) VALUES ('X', 5)"))
    crear_tablas()
    columnas = {c["name"] for c in inspect(motor()).get_columns("material")}
    assert columnas == {c.name for c in Base.metadata.tables["material"].columns}
    with motor().begin() as con:
        assert con.execute(text("SELECT codigo, stock, controlado, unidad FROM material")).one() == ("X", 5.0, 1, "ud")


def test_poda_de_planes_antiguos(cliente, con_plan):
    from sqlalchemy import func, select

    from hidral_plan.db import sesion
    from hidral_plan.modelos import AsignacionPlan, Plan

    h = con_plan
    assert cliente.put("/api/configuracion/retencion_planes", headers=h, json={"valor": {"oficiales": 2, "simulaciones": 1}}).status_code == 200
    for _ in range(5):
        assert cliente.post("/api/plan/generar", headers=h, json={}).status_code == 200
    for _ in range(3):
        assert cliente.post("/api/plan/simulaciones/escenario", headers=h, json={"escenario": {"pesos_prioridad": {"holgura": 0.4}}}).status_code == 200
    with sesion() as s:
        assert s.scalar(select(func.count(Plan.id)).where(Plan.tipo == "OFICIAL")) == 3  # activo + 2 archivados
        assert s.scalar(select(func.count(Plan.id)).where(Plan.tipo == "SIMULACION")) == 1
        huerfanas = s.scalar(select(func.count(AsignacionPlan.id)).where(~AsignacionPlan.plan_id.in_(select(Plan.id))))
        assert huerfanas == 0
    assert cliente.get("/api/plan/historico", headers=h).status_code == 200


def test_quitar_maquina_libera_lo_fijado_y_carga_sin_personas(cliente, con_plan):
    h = con_plan
    a = cliente.get("/api/plan/activo/gantt", headers=h).json()["asignaciones"][0]
    rec = next(r for r in cliente.get("/api/recursos", headers=h).json() if r["codigo"] == a["recurso"])
    assert cliente.patch(f"/api/operaciones/{a['operacion_id']}", headers=h, json={"maquina": rec["codigo"]}).status_code == 200
    r = cliente.delete(f"/api/recursos/{rec['id']}", headers=h).json()
    assert r["liberadas"] >= 1 and "pueden ir ahora" in r["motivo"]
    assert cliente.get(f"/api/operaciones/{a['operacion_id']}", headers=h).status_code == 200
    # una sección cuyas máquinas necesitan operario y nadie está cualificado: sin capacidad
    ops = cliente.get("/api/operarios", headers=h).json()
    seccion = rec["seccion"]
    maquinas = {x["codigo"] for x in cliente.get("/api/recursos", headers=h).json() if x["seccion"] == seccion}
    for o in ops:
        if any(c["recurso"] in maquinas for c in o["cualificaciones"]):
            assert cliente.patch(f"/api/operarios/{o['id']}", headers=h, json={"recursos": [c["recurso"] for c in o["cualificaciones"] if c["recurso"] and c["recurso"] not in maquinas], "operaciones": []}).status_code == 200
    eq = next(x for x in cliente.get("/api/carga", headers=h).json()["secciones"] if x["seccion"] == seccion)
    assert eq["capacidad_personas_h"] == 0 and eq["capacidad_h"] == 0 and eq["limitada_por"] in ("nadie cualificado", "sin capacidad")


def test_ocultar_datos_personales():
    from hidral_plan.ingesta.normalizacion import OCULTO, ocultar_datos_personales

    texto = "OBSERVACIONES /\nREMARKS:\nFulano TF 600 11 22 33 / fulano@ejemplo.com\nTfno. EMPRESA (CENTRAL): 96500000000\nCLIENTE /\n2060131 917251 EH-36747 3001000/4\nR=2670 F=230"
    limpio = ocultar_datos_personales(texto)
    assert "600 11 22 33" not in limpio and "@" not in limpio and "96500000000" not in limpio and "Fulano" not in limpio
    assert limpio.count(OCULTO) == 2
    # códigos de artículo, OF y parámetros no se tocan
    assert "2060131 917251 EH-36747 3001000/4" in limpio and "R=2670 F=230" in limpio
    assert ocultar_datos_personales(None) is None


def test_limpieza_unica_de_bases_anteriores(entorno):
    from hidral_plan.db import sesion
    from hidral_plan.modelos import Documento, PaginaDocumento
    from hidral_plan.servicios.privacidad import limpiar_datos_personales

    with sesion() as s:
        d = Documento(nombre="x.pdf", hash_sha256="a" * 64, tamano_bytes=1, usuario_carga="x", ruta_almacen="/no")
        s.add(d)
        s.flush()
        s.add(PaginaDocumento(documento_id=d.id, numero=1, bloque=1, tipo="PACKING_LIST", metodo_extraccion="TEXTO", texto="Contacto: ana@ejemplo.com\nBULTO 1"))
    with sesion() as s:
        assert limpiar_datos_personales(s) == 1
    with sesion() as s:
        assert limpiar_datos_personales(s) == 0  # solo una vez
        assert "@" not in s.scalar(__import__("sqlalchemy").select(PaginaDocumento.texto))
