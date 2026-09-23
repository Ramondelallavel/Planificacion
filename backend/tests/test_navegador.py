"""Edición navegador: el adaptador ASGI sin hilos, el procesamiento por bloques y PBKDF2 sin OpenSSL.

Se ejecutan en CPython: el código es el mismo que corre en Pyodide."""

from __future__ import annotations

import asyncio
import hashlib
import importlib
import json
import os

import pytest

from .conftest import PDF_REAL, RAIZ
from .generador_pdf import Aparato as ApGen
from .generador_pdf import OpcionesTanda, generar_tanda


def test_pbkdf2_sin_openssl_coincide(monkeypatch):
    from hidral_plan import seguridad

    sal = os.urandom(16)
    esperado = hashlib.pbkdf2_hmac("sha256", b"clave", sal, 1500)
    monkeypatch.delattr(hashlib, "pbkdf2_hmac")
    assert seguridad._pbkdf2_sha256(b"clave", sal, 1500) == esperado
    h = seguridad.hash_clave("hidral")
    assert seguridad.verificar_clave("hidral", h) and not seguridad.verificar_clave("otra", h)


@pytest.fixture()
def navegador(tmp_path, monkeypatch):
    monkeypatch.setenv("HIDRAL_NAVEGADOR_DATOS", str(tmp_path / "datos"))
    for k in ("HIDRAL_DB_URL", "HIDRAL_ALMACEN_DIR", "HIDRAL_AHORA"):
        monkeypatch.delenv(k, raising=False)
    from hidral_plan import navegador as nav

    nav = importlib.reload(nav)
    yield nav
    from hidral_plan.db import reiniciar_motor

    reiniciar_motor()
    for k in list(os.environ):
        if k.startswith("HIDRAL_") and k != "HIDRAL_PDF_EJEMPLO":
            monkeypatch.delenv(k, raising=False)


def _pedir(nav, metodo, ruta, token=None, json_=None, cuerpo=None, tipo=None):
    cab = {}
    if token:
        cab["authorization"] = f"Bearer {token}"
    if json_ is not None:
        cab["content-type"] = "application/json"
        cuerpo = json.dumps(json_).encode()
    if tipo:
        cab["content-type"] = tipo
    r = asyncio.run(nav.peticion(metodo, "/api" + ruta, cab, cuerpo))
    return r["estado"], (json.loads(r["cuerpo"]) if r["cabeceras"].get("content-type", "").startswith("application/json") else r["cuerpo"])


def test_api_completa_sin_servidor_ni_hilos(navegador, tmp_path):
    nav = navegador
    config = (RAIZ / "config" / "fabrica_ejemplo.yaml").read_text(encoding="utf-8")
    assert nav.preparar("secreto", config, "2026-09-21T07:00:00") == {"base_nueva": True}
    # los hilos quedan sustituidos por ejecución en línea
    import anyio.to_thread

    assert asyncio.run(anyio.to_thread.run_sync(lambda: 42)) == 42
    estado, s = _pedir(nav, "POST", "/auth/login", json_={"usuario": "planificador", "clave": "hidral"})
    assert estado == 200
    token = s["token"]
    # subida multipart como la hace el navegador
    pdf = tmp_path / "t.pdf"
    generar_tanda(pdf, OpcionesTanda(aparatos=[ApGen("40001"), ApGen("40002")]))
    frontera = "----hidral"
    cuerpo = (f'--{frontera}\r\nContent-Disposition: form-data; name="fichero"; filename="t.pdf"\r\nContent-Type: application/pdf\r\n\r\n').encode() + pdf.read_bytes() + f"\r\n--{frontera}--\r\n".encode()
    estado, r = _pedir(nav, "POST", "/documentos", token, cuerpo=cuerpo, tipo=f"multipart/form-data; boundary={frontera}")
    assert estado == 202, r
    # el worker avanza el procesamiento bloque a bloque
    pasos = []
    while (p := nav.procesar_paso()) is not None:
        pasos.append(p)
    assert pasos[-1]["estado"] == "COMPLETADO" and pasos[-1]["paginas"] == pasos[-1]["total"]
    estado, r = _pedir(nav, "POST", "/plan/generar", token, json_={})
    assert estado == 200 and r["kpis"]["planificadas"] > 0
    estado, img = _pedir(nav, "GET", "/documentos/1/paginas/1/imagen", token)
    assert estado == 200 and img[:4] == b"\x89PNG"
    # cerrar y reabrir (copia/restauración de la base) conserva los datos
    nav.cerrar_conexiones()
    nav.reabrir()
    estado, t = _pedir(nav, "GET", "/tandas", token)
    assert estado == 200 and len(t) == 1


def test_procesamiento_limitado_por_bloques(fabrica, tmp_path, monkeypatch):
    monkeypatch.setenv("HIDRAL_BLOQUE_MAX", "5")
    from hidral_plan.config import reiniciar_ajustes
    from hidral_plan.db import sesion
    from hidral_plan.ingesta.pipeline import procesar_trabajo, registrar_documento
    from hidral_plan.modelos import TrabajoProcesamiento

    reiniciar_ajustes()
    pdf = tmp_path / "t.pdf"
    generar_tanda(pdf, OpcionesTanda(aparatos=[ApGen("40001", ofs_relleno=20)]))
    r = registrar_documento(pdf, "t.pdf", "test")
    procesar_trabajo(r.trabajo_id, max_bloques=1)
    with sesion() as s:
        t = s.get(TrabajoProcesamiento, r.trabajo_id)
        assert t.estado == "PROCESANDO" and 0 < t.paginas_procesadas < t.paginas_totales
    procesar_trabajo(r.trabajo_id)
    with sesion() as s:
        t = s.get(TrabajoProcesamiento, r.trabajo_id)
        assert t.estado == "COMPLETADO" and t.paginas_procesadas == t.paginas_totales


@pytest.mark.skipif(not PDF_REAL.exists(), reason="PDF real no disponible")
def test_carga_de_ejemplo_genera_plan(navegador):
    nav = navegador
    nav.preparar("secreto", (RAIZ / "config" / "fabrica_ejemplo.yaml").read_text(encoding="utf-8"), "2026-09-21T07:00:00")
    r = nav.cargar_ejemplo(PDF_REAL.read_bytes(), PDF_REAL.name)
    assert r["plan_id"]
