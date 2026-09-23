"""Gestión de tandas, carga de trabajo, recursos y materiales desde la API."""

from __future__ import annotations

import pytest
from sqlalchemy import func, select

from hidral_plan.db import sesion
from hidral_plan.modelos import AsignacionPlan, Documento, LineaOF, Operacion, OrdenFabricacion, PaginaDocumento

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
    assert r.status_code == 200
    return {"Authorization": f"Bearer {r.json()['token']}"}


def _importar(c, h, ruta) -> dict:
    from hidral_plan.ingesta.cola import reclamar_trabajo
    from hidral_plan.ingesta.pipeline import procesar_trabajo

    r = c.post("/api/documentos", headers=h, files={"fichero": (ruta.name, ruta.read_bytes(), "application/pdf")}).json()
    if r.get("trabajo_id") and not r["duplicado"]:
        procesar_trabajo(reclamar_trabajo("test"))
    return r


def _dos_tandas(c, h, tmp):
    a, b = tmp / "t9001.pdf", tmp / "t9002.pdf"
    generar_tanda(a, OpcionesTanda(tanda="9001", aparatos=[ApGen("70001"), ApGen("70002")]))
    generar_tanda(b, OpcionesTanda(tanda="9002", base_of=810000, aparatos=[ApGen("71001")]))
    _importar(c, h, a)
    _importar(c, h, b)
    tandas = {t["numero"]: t for t in c.get("/api/tandas", headers=h).json()}
    return a, b, tandas


def test_eliminar_tanda_y_volver_a_importarla(cliente, fabrica):
    h = _login(cliente)
    a, _b, tandas = _dos_tandas(cliente, h, fabrica)
    assert cliente.post("/api/plan/generar", headers=h, json={}).status_code == 200
    with sesion() as s:
        ofs_a = s.scalar(select(func.count(OrdenFabricacion.id)).where(OrdenFabricacion.tanda_id == tandas["9001"]["id"]))
        docs_antes = s.scalar(select(func.count(Documento.id)))
    assert ofs_a > 0
    assert cliente.delete(f"/api/tandas/{tandas['9001']['id']}", headers=_login(cliente, "op01")).status_code == 403
    r = cliente.delete(f"/api/tandas/{tandas['9001']['id']}?motivo=pedido anulado", headers=h)
    assert r.status_code == 200, r.text
    r = r.json()
    assert r["ofs"] == ofs_a and r["aparatos"] == 2 and r["documentos"] == ["t9001.pdf"] and r["plan_id"]
    # la otra tanda sigue intacta y el plan nuevo solo la contiene a ella
    assert [t["numero"] for t in cliente.get("/api/tandas", headers=h).json()] == ["9002"]
    gantt = cliente.get("/api/plan/activo/gantt", headers=h).json()
    assert gantt["asignaciones"] and {x["tanda"] for x in gantt["asignaciones"]} == {"9002"}
    with sesion() as s:
        assert s.scalar(select(func.count(Documento.id))) == docs_antes - 1
        assert not s.scalar(select(func.count(OrdenFabricacion.id)).where(OrdenFabricacion.numero.like("8000%")))
        huerfanas = s.scalar(select(func.count(Operacion.id)).where(~Operacion.of_id.in_(select(OrdenFabricacion.id))))
        assert huerfanas == 0 and s.scalar(select(func.count(LineaOF.id)).where(~LineaOF.of_id.in_(select(OrdenFabricacion.id)))) == 0
        assert s.scalar(select(func.count(AsignacionPlan.id)).where(~AsignacionPlan.of_id.in_(select(OrdenFabricacion.id)))) == 0
        assert s.scalar(select(func.count(PaginaDocumento.id)).where(~PaginaDocumento.documento_id.in_(select(Documento.id)))) == 0
    assert any(x["accion"] == "ELIMINAR_TANDA" and x["motivo"] == "pedido anulado" for x in cliente.get("/api/auditoria", headers=h).json())
    # el mismo PDF se puede volver a importar: ya no es un duplicado
    r = _importar(cliente, h, a)
    assert not r["duplicado"]
    assert sorted(t["numero"] for t in cliente.get("/api/tandas", headers=h).json()) == ["9001", "9002"]


def test_tanda_con_trabajo_fichado_se_archiva(cliente, fabrica):
    h = _login(cliente)
    _a, _b, tandas = _dos_tandas(cliente, h, fabrica)
    assert cliente.post("/api/plan/generar", headers=h, json={}).status_code == 200
    ho, hj = _login(cliente, "op01"), _login(cliente, "jefe")
    t = cliente.get("/api/operario/trabajo", headers=ho).json()
    sig = t["siguiente"]
    assert cliente.post("/api/operario/iniciar", headers=hj, json={"operacion_id": sig["operacion_id"], "operario_id": t["operario"]["id"], "autorizado_por": "jefe"}).status_code == 200
    tanda_id = sig["tanda"]
    numero = next(x["numero"] for x in cliente.get("/api/tandas", headers=h).json() if x["id"] == tanda_id)
    r = cliente.delete(f"/api/tandas/{tanda_id}", headers=h)
    assert r.status_code == 409 and "Archívala" in r.json()["detail"]
    r = cliente.patch(f"/api/tandas/{tanda_id}", headers=h, json={"estado": "ARCHIVADA", "motivo": "cerrada con el cliente"})
    assert r.status_code == 200 and r.json()["incluida_en_plan"] is False
    assert cliente.post("/api/plan/generar", headers=h, json={}).status_code == 200
    en_plan = {x["tanda"] for x in cliente.get("/api/plan/activo/gantt", headers=h).json()["asignaciones"]}
    assert numero not in en_plan and en_plan
    assert cliente.patch(f"/api/tandas/{tanda_id}", headers=h, json={"estado": "OTRA"}).status_code == 400
    assert cliente.patch(f"/api/tandas/{tanda_id}", headers=h, json={"estado": "ACTIVA"}).json()["incluida_en_plan"] is True


def test_cambiar_semana_de_tanda_y_de_aparato(cliente, fabrica):
    h = _login(cliente)
    _a, _b, tandas = _dos_tandas(cliente, h, fabrica)
    tid = tandas["9001"]["id"]
    assert cliente.patch(f"/api/tandas/{tid}", headers=h, json={"semana": "2026X"}).status_code == 400
    r = cliente.patch(f"/api/tandas/{tid}", headers=h, json={"semana": "202642", "producto": "Nuevo producto"}).json()
    assert r["semana"] == "202642"
    det = cliente.get(f"/api/tandas/{tid}", headers=h).json()
    assert det["producto"] == "Nuevo producto" and {a["semana"] for a in det["aparatos"]} == {"202642"}
    assert {o["semana"] for o in cliente.get(f"/api/ofs?tanda_id={tid}&limite=500", headers=h).json()["items"]} == {"202642"}
    ap = det["aparatos"][0]
    r = cliente.patch(f"/api/aparatos/{ap['id']}", headers=h, json={"semana": "202641", "motivo": "adelanta el cliente"}).json()
    assert r["aparatos"] == 1 and r["ofs"] >= 1
    assert cliente.get(f"/api/aparatos/{ap['id']}", headers=h).json()["semana"] == "202641"


def test_eliminar_documento_sin_tanda(cliente, fabrica):
    h = _login(cliente)
    malo = fabrica / "roto.pdf"
    malo.write_bytes(b"esto no es un pdf")
    r = cliente.post("/api/documentos", headers=h, files={"fichero": ("roto.pdf", malo.read_bytes(), "application/pdf")}).json()
    assert cliente.delete(f"/api/documentos/{r['documento_id']}", headers=h).status_code == 200
    assert cliente.get(f"/api/documentos/{r['documento_id']}", headers=h).status_code == 404
    _a, _b, tandas = _dos_tandas(cliente, h, fabrica)
    doc = tandas["9001"]["documento_id"]
    assert cliente.delete(f"/api/documentos/{doc}", headers=h).status_code == 409


# ------------------------------------------------------------------ carga de trabajo
def _una_tanda(c, h, tmp):
    ruta = tmp / "t9001.pdf"
    generar_tanda(ruta, OpcionesTanda(tanda="9001", aparatos=[ApGen("70001"), ApGen("70002")]))
    _importar(c, h, ruta)
    return c.get("/api/tandas", headers=h).json()[0]


def test_editar_anadir_y_quitar_operaciones(cliente, fabrica):
    h = _login(cliente)
    _una_tanda(cliente, h, fabrica)
    of = cliente.get("/api/ofs?limite=1", headers=h).json()["items"][0]
    det = cliente.get(f"/api/ofs/{of['id']}", headers=h).json()
    op = det["operaciones"][0]
    r = cliente.patch(f"/api/operaciones/{op['id']}", headers=h, json={"minutos": 123, "motivo": "pieza más compleja"})
    assert r.status_code == 200 and r.json()["minutos"] == 123
    assert cliente.patch(f"/api/operaciones/{op['id']}", headers=h, json={"minutos": 0}).status_code == 400
    assert cliente.patch(f"/api/operaciones/{op['id']}", headers=h, json={"maquina": "NO-EXISTE"}).status_code == 400
    assert cliente.patch("/api/operaciones/999999", headers=h, json={"minutos": 5}).status_code == 404
    # recalcular los tiempos estándar no pisa lo que se fijó a mano
    cliente.post("/api/tiempos-estandar/recalcular", headers=h, json={})
    assert cliente.get(f"/api/operaciones/{op['id']}", headers=h).json()["duracion_estimada_min"] == 123
    nueva = cliente.post(f"/api/ofs/{of['id']}/operaciones", headers=h, json={"tipo": "retrabajo", "minutos": 45, "despues_de": op["id"], "motivo": "defecto de soldadura"}).json()
    ops = cliente.get(f"/api/ofs/{of['id']}", headers=h).json()["operaciones"]
    assert [o["id"] for o in ops].index(nueva["id"]) == 1 and [o["secuencia"] for o in ops] == [10 * (i + 1) for i in range(len(ops))]
    assert nueva["tipo"] == "RETRABAJO"
    assert cliente.delete(f"/api/operaciones/{nueva['id']}", headers=h).status_code == 200
    assert len(cliente.get(f"/api/ofs/{of['id']}", headers=h).json()["operaciones"]) == len(ops) - 1
    assert cliente.patch(f"/api/operaciones/{op['id']}", headers=_login(cliente, "op01"), json={"minutos": 5}).status_code == 403


def test_of_a_mano_entra_en_el_plan_y_se_puede_borrar(cliente, fabrica):
    h = _login(cliente)
    t = _una_tanda(cliente, h, fabrica)
    maquinas = cliente.get("/api/recursos", headers=h).json()
    m = next(r for r in maquinas if r["tipo"] == "MAQUINA" and r["operaciones"])
    r = cliente.post("/api/ofs", headers=h, json={"descripcion": "Reparación de bastidor", "semana": "202640", "urgente": True, "operaciones": [{"tipo": m["operaciones"][0], "minutos": 90, "maquina": m["codigo"]}, {"tipo": "MONTAJE", "minutos": 30, "seccion": m["seccion"]}]})
    assert r.status_code == 200, r.text
    of = r.json()
    assert of["numero"].startswith("M") and of["tanda"] == "VARIOS" and of["horas"] == 2.0
    # también dentro de una tanda existente
    r2 = cliente.post("/api/ofs", headers=h, json={"numero": "X-1", "tanda_id": t["id"], "operaciones": [{"tipo": "MONTAJE", "minutos": 60, "seccion": m["seccion"]}]}).json()
    assert r2["tanda"] == "9001"
    assert cliente.post("/api/ofs", headers=h, json={"numero": "X-1", "tanda_id": t["id"], "operaciones": [{"tipo": "MONTAJE", "minutos": 60, "seccion": m["seccion"]}]}).status_code == 400
    assert cliente.post("/api/ofs", headers=h, json={"operaciones": []}).status_code == 400
    assert cliente.post("/api/plan/generar", headers=h, json={}).status_code == 200
    gantt = cliente.get("/api/plan/activo/gantt", headers=h).json()["asignaciones"]
    mia = [a for a in gantt if a["of"] == of["numero"]]
    assert len(mia) == 2 and mia[0]["recurso"] == m["codigo"]
    assert cliente.delete(f"/api/ofs/{of['id']}", headers=h).status_code == 200
    assert cliente.get(f"/api/ofs/{of['id']}", headers=h).status_code == 404


def test_mover_carga_entre_maquinas_y_rendimiento(cliente, fabrica):
    h = _login(cliente)
    _una_tanda(cliente, h, fabrica)
    assert cliente.post("/api/plan/generar", headers=h, json={}).status_code == 200
    carga = cliente.get("/api/carga?dias=14", headers=h).json()
    con_demanda = [x for x in carga["secciones"] if x["demanda_h"] > 0]
    assert con_demanda and all(x["capacidad_h"] >= 0 for x in carga["secciones"])
    sec = max(con_demanda, key=lambda x: x["demanda_h"])
    # rendimiento del 125 %: la misma carga pesa un 20 % menos
    assert cliente.put("/api/carga/rendimiento", headers=h, json={"seccion": sec["seccion"], "rendimiento": 125}).status_code == 200
    despues = next(x for x in cliente.get("/api/carga", headers=h).json()["secciones"] if x["seccion"] == sec["seccion"])
    assert despues["rendimiento"] == 125 and abs(despues["demanda_h"] - sec["demanda_h"] * 0.8) <= 0.2 and despues["demanda_base_h"] == sec["demanda_h"]
    assert cliente.put("/api/carga/rendimiento", headers=h, json={"seccion": sec["seccion"], "rendimiento": 5}).status_code == 400
    cliente.put("/api/carga/rendimiento", headers=h, json={"seccion": sec["seccion"], "rendimiento": 100})
    # mover la carga planificada en una máquina a otra de la misma sección que haga lo mismo
    gantt = cliente.get("/api/plan/activo/gantt", headers=h).json()["asignaciones"]
    recursos = cliente.get("/api/recursos", headers=h).json()
    origen = destino = None
    for a in gantt:
        ro = next(r for r in recursos if r["codigo"] == a["recurso"])
        otras = [r for r in recursos if r["seccion"] == ro["seccion"] and r["id"] != ro["id"] and (not r["operaciones"] or a["tipo"] in r["operaciones"])]
        if otras:
            origen, destino = ro, otras[0]
            break
    if origen is None:
        pytest.skip("la fábrica de ejemplo no tiene dos máquinas intercambiables")
    previa = cliente.post("/api/carga/mover?aplicar=false", headers=h, json={"desde_maquina": origen["codigo"], "hacia_maquina": destino["codigo"]}).json()
    assert previa["operaciones"] > 0 and not previa["aplicado"]
    hecho = cliente.post("/api/carga/mover", headers=h, json={"desde_maquina": origen["codigo"], "hacia_maquina": destino["codigo"], "motivo": "equilibrar"}).json()
    assert hecho["aplicado"] and hecho["operaciones"] == previa["operaciones"]
    assert cliente.post("/api/plan/generar", headers=h, json={}).status_code == 200
    gantt = cliente.get("/api/plan/activo/gantt", headers=h).json()["asignaciones"]
    assert not [a for a in gantt if a["recurso"] == origen["codigo"] and a["estado"] != "TERMINADA"] or previa["n_rechazadas"]
    assert cliente.post("/api/carga/mover", headers=h, json={"desde_maquina": origen["codigo"], "hacia_maquina": origen["codigo"]}).status_code == 400


# ------------------------------------------------------------------ recursos
def test_duplicar_y_quitar_maquinas(cliente, fabrica):
    h = _login(cliente)
    _una_tanda(cliente, h, fabrica)
    assert cliente.post("/api/plan/generar", headers=h, json={}).status_code == 200
    usada = cliente.get("/api/plan/activo/gantt", headers=h).json()["asignaciones"][0]["recurso"]
    rec = next(r for r in cliente.get("/api/recursos", headers=h).json() if r["codigo"] == usada)
    antes = next(x for x in cliente.get("/api/carga", headers=h).json()["secciones"] if x["seccion"] == rec["seccion"])
    r = cliente.post(f"/api/recursos/{rec['id']}/duplicar", headers=h, json={"cantidad": 2}).json()
    assert len(r["nuevos"]) == 2 and all(c.startswith(rec["codigo"].rsplit("-", 1)[0]) for c in r["nuevos"])
    despues = next(x for x in cliente.get("/api/carga", headers=h).json()["secciones"] if x["seccion"] == rec["seccion"])
    assert despues["capacidad_maquinas_h"] > antes["capacidad_maquinas_h"]
    # los operarios cualificados en la original lo están en las copias
    ops = cliente.get("/api/operarios", headers=h).json()
    en_original = {o["id"] for o in ops if any(c["recurso"] == rec["codigo"] for c in o["cualificaciones"])}
    en_copia = {o["id"] for o in ops if any(c["recurso"] == r["nuevos"][0] for c in o["cualificaciones"])}
    assert en_original and en_original == en_copia
    nueva = next(x for x in cliente.get("/api/recursos", headers=h).json() if x["codigo"] == r["nuevos"][0])
    assert cliente.delete(f"/api/recursos/{nueva['id']}", headers=h).json()["borrado"] is True
    # la que está en el plan no se borra: se da de baja
    q = cliente.delete(f"/api/recursos/{rec['id']}", headers=h).json()
    assert q["borrado"] is False and q["desactivado"] is True
    assert next(x for x in cliente.get("/api/recursos", headers=h).json() if x["id"] == rec["id"])["activo"] is False
    assert cliente.post(f"/api/recursos/{rec['id']}/duplicar", headers=h, json={"cantidad": 99}).status_code == 400


def test_alta_de_operarios_en_lote_y_bajas(cliente, fabrica):
    h = _login(cliente)
    ops = cliente.get("/api/operarios", headers=h).json()
    modelo = next(o for o in ops if o["codigo"] == "OP01")
    r = cliente.post("/api/operarios/lote", headers=h, json={"cantidad": 3, "copiar_de": modelo["id"], "nombre": "Refuerzo soldadura"})
    assert r.status_code == 200, r.text
    creados = r.json()["creados"]
    assert len(creados) == 3
    nuevos = [o for o in cliente.get("/api/operarios", headers=h).json() if o["codigo"] in creados]
    assert {o["turno"] for o in nuevos} == {modelo["turno"]} and all(o["cualificaciones"] == modelo["cualificaciones"] for o in nuevos)
    assert nuevos[0]["nombre"] == "Refuerzo soldadura 1"
    # por sección: cualificados en todas sus máquinas
    sec = cliente.post("/api/operarios/lote", headers=h, json={"cantidad": 1, "seccion": "LCH", "turno": modelo["turno"]}).json()
    maquinas_lch = {x["codigo"] for x in cliente.get("/api/recursos", headers=h).json() if x["seccion"] == "LCH" and x["activo"] and x["tipo"] != "PROGRAMACION"}
    assert set(sec["recursos"]) == maquinas_lch
    assert cliente.post("/api/operarios/lote", headers=h, json={"cantidad": 1}).status_code == 400
    assert cliente.post("/api/operarios/lote", headers=h, json={"cantidad": 1, "copiar_de": modelo["id"], "turno": "ZZ"}).status_code == 400
    assert cliente.delete(f"/api/operarios/{nuevos[0]['id']}", headers=h).json()["borrado"] is True
    # op01 tiene usuario: se da de baja, no se borra
    assert cliente.delete(f"/api/operarios/{modelo['id']}", headers=h).json()["desactivado"] is True


# ------------------------------------------------------------------ materiales
def _consumos(of_ids_cantidades: dict[int, float], codigo: str = "TUBO-1") -> None:
    with sesion() as s:
        for of_id, cantidad in of_ids_cantidades.items():
            of = s.get(OrdenFabricacion, of_id)
            of.consumos = [{"articulo": codigo, "descripcion": "TUBO DE PRUEBA", "total": cantidad, "total_texto": str(cantidad), "pagina": 1, "tipo": "Consumidos"}]


def test_materiales_bloquean_y_liberan_ofs(cliente, fabrica):
    from datetime import datetime, timedelta

    from .conftest import AHORA

    h = _login(cliente)
    _una_tanda(cliente, h, fabrica)
    assert cliente.post("/api/plan/generar", headers=h, json={}).status_code == 200
    gantt = cliente.get("/api/plan/activo/gantt", headers=h).json()["asignaciones"]
    primeras: dict[int, str] = {}
    for a in sorted(gantt, key=lambda a: a["inicio"]):
        primeras.setdefault(a["of_id"], a["inicio"])
    # la primera en empezar y otra que empiece estrictamente después (sin empates de orden)
    a_id = next(iter(primeras))
    b_id = next(k for k, v in primeras.items() if v > primeras[a_id])
    _consumos({a_id: 10, b_id: 5})
    lista = cliente.get("/api/materiales", headers=h).json()
    fila = next(m for m in lista["materiales"] if m["codigo"] == "TUBO-1")
    assert fila["necesidad"] == 15 and fila["ofs"] == 2 and not fila["controlado"]
    # sin controlar, nada cambia; con stock 10 la primera tiene material y la segunda no
    assert cliente.post("/api/materiales", headers=h, json={"codigo": "TUBO-1", "stock": 10, "unidad": "m"}).status_code == 200
    r = cliente.post("/api/materiales/calcular", headers=h).json()
    assert r["con_material"] == 1 and r["bloqueadas"] == 1 and r["plan_id"]
    assert cliente.get(f"/api/ofs/{a_id}", headers=h).json()["material_disponible"] is True
    assert cliente.get(f"/api/ofs/{b_id}", headers=h).json()["material_disponible"] is False
    no_plan = {n["of_id"] for n in cliente.get("/api/plan/activo/no-planificadas", headers=h).json() if n["motivo"] == "ESPERANDO_MATERIAL"}
    assert b_id in no_plan
    # llega un pedido el miércoles: la segunda se planifica desde ese momento
    llegada = (AHORA + timedelta(days=2)).replace(hour=10, minute=0)
    assert cliente.post("/api/materiales/entradas", headers=h, json={"codigo": "TUBO-1", "cantidad": 8, "fecha_prevista": llegada.isoformat(), "referencia": "PED-77"}).status_code == 200
    r = cliente.post("/api/materiales/calcular", headers=h).json()
    assert r["con_fecha"] == 1 and r["bloqueadas"] == 0
    inicios = [datetime.fromisoformat(a["inicio"]) for a in cliente.get("/api/plan/activo/gantt", headers=h).json()["asignaciones"] if a["of_id"] == b_id]
    assert inicios and min(inicios) >= llegada
    # se recibe: stock 18, las dos cubiertas
    e = next(m for m in cliente.get("/api/materiales", headers=h).json()["materiales"] if m["codigo"] == "TUBO-1")["entradas"][0]
    assert cliente.post(f"/api/materiales/entradas/{e['id']}/recibir", headers=h).json()["stock"] == 18
    assert cliente.post(f"/api/materiales/entradas/{e['id']}/recibir", headers=h).status_code == 409
    r = cliente.post("/api/materiales/calcular?replanificar=false", headers=h).json()
    assert r["con_material"] == 2 and "plan_id" not in r
    det = cliente.get("/api/materiales/detalle?codigo=TUBO-1", headers=h).json()
    assert [c["estado"] for c in det["consumidores"]] == ["CUBIERTA", "CUBIERTA"]
    # deja de controlarse: las OF vuelven a «sin dato»
    assert cliente.delete("/api/materiales?codigo=TUBO-1", headers=h).status_code == 200
    assert cliente.post("/api/materiales/calcular?replanificar=false", headers=h).json()["liberadas"] == 2
    assert cliente.get(f"/api/ofs/{b_id}", headers=h).json()["material_disponible"] is None
    assert cliente.post("/api/materiales", headers=_login(cliente, "op01"), json={"codigo": "X", "stock": 1}).status_code == 403


def test_importar_stock_csv(cliente, fabrica):
    h = _login(cliente)
    csv_txt = "codigo;descripcion;unidad;stock\nTUBO-1;Tubo;m;1.234,5\nPERFIL-2;Perfil;m;20\n;sin código;;3\n"
    r = cliente.post("/api/materiales/importar", headers=h, files={"fichero": ("stock.csv", csv_txt.encode(), "text/csv")}).json()
    assert r["materiales"] == 2 and len(r["errores"]) == 1
    filas = {m["codigo"]: m for m in cliente.get("/api/materiales", headers=h).json()["materiales"]}
    assert filas["TUBO-1"]["stock"] == 1234.5 and filas["PERFIL-2"]["unidad"] == "m" and filas["PERFIL-2"]["controlado"]
