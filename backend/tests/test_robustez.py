"""Robustez: se ataca cada ruta de la API con valores extremos o maliciosos, generados a partir del
esquema OpenAPI (textos enormes, NaN e infinito, fechas límite, identificadores fuera de rango,
inyecciones…). La regla: ninguna petición puede acabar en un error 500 ni tumbar el servidor;
lo inválido se rechaza con un 4xx y un mensaje, y lo válido se procesa."""

from __future__ import annotations

import json
import re

import pytest

from .generador_pdf import Aparato as ApGen
from .generador_pdf import OpcionesTanda, generar_tanda

NAN, INF = "__NAN__", "__INF__"

MUTACIONES: dict[str, list] = {
    "string": ["", "x" * 5000, "'; DROP TABLE tanda;--", "<script>alert(1)</script>", "nulo\x00medio", "../../etc/passwd", "💥" * 60],
    "integer": [-1, 0, 2**31, 2**63, 10**30],
    "number": [-1.5, 0, 1e308, -1e308, NAN, INF],
    "date-time": ["0001-01-01T00:00:00", "9999-12-31T23:59:59", "2026-02-30T00:00:00"],
    "date": ["0001-01-01", "9999-12-31"],
    "boolean": [True, False],
    "array": [[], ["x" * 300] * 3, [None]],
    "object": [{}, {"x" * 50: "y"}],
}
BASE = {"string": "PRUEBA", "integer": 1, "number": 1.0, "date-time": "2026-09-22T08:00:00", "date": "2026-09-26", "boolean": False, "array": [], "object": {}}
PATH_VALORES = {"integer": ["1", "0", "-1", "999999999999", "abc"], "string": ["X", "x" * 300, "..%2F..%2Fsecreto", "2026-13-45", "%00"]}


def _tipo(esquema: dict, spec: dict) -> str:
    if "$ref" in esquema:
        return "object"
    if "anyOf" in esquema:
        for x in esquema["anyOf"]:
            if x.get("type") != "null":
                return _tipo(x, spec)
    fmt = esquema.get("format")
    if fmt in ("date-time", "date"):
        return fmt
    return esquema.get("type", "string")


def _resolver(ref: str, spec: dict) -> dict:
    return spec["components"]["schemas"][ref.split("/")[-1]]


def _cuerpo_base(esquema: dict, spec: dict) -> dict:
    cuerpo = {}
    for nombre, prop in esquema.get("properties", {}).items():
        t = _tipo(prop, spec)
        if nombre in esquema.get("required", []) or t != "object":
            cuerpo[nombre] = BASE[t] if t in BASE else "PRUEBA"
    return cuerpo


def _json(cuerpo) -> str:
    texto = json.dumps(cuerpo, ensure_ascii=False)
    return texto.replace(f'"{NAN}"', "NaN").replace(f'"{INF}"', "Infinity")


@pytest.fixture()
def cliente(fabrica):
    from fastapi.testclient import TestClient

    from hidral_plan.api.app import crear_app

    with TestClient(crear_app()) as c:
        yield c


@pytest.fixture()
def admin(cliente, fabrica):
    from hidral_plan.ingesta.cola import reclamar_trabajo
    from hidral_plan.ingesta.pipeline import procesar_trabajo

    r = cliente.post("/api/auth/login", json={"usuario": "admin", "clave": "hidral"})
    h = {"Authorization": f"Bearer {r.json()['token']}"}
    ruta = fabrica / "t.pdf"
    generar_tanda(ruta, OpcionesTanda(aparatos=[ApGen("70001"), ApGen("70002")]))
    cliente.post("/api/documentos", headers=h, files={"fichero": ("t.pdf", ruta.read_bytes(), "application/pdf")})
    procesar_trabajo(reclamar_trabajo("test"))
    assert cliente.post("/api/plan/generar", headers=h, json={}).status_code == 200
    return h


def _peticiones(spec: dict):
    """(método, ruta, consulta, cuerpo_json|None, ficheros|None, descripción) para cada mutación."""
    orden = {"get": 0, "post": 1, "put": 1, "patch": 2, "delete": 3}
    ops = sorted(((m, p, op) for p, d in spec["paths"].items() for m, op in d.items()), key=lambda x: (orden.get(x[0], 9), x[1]))
    for metodo, ruta, op in ops:
        if ruta in ("/api/auth/login",) or not ruta.startswith("/api/"):
            continue  # el inicio de sesión se prueba aparte (bloquearía la cuenta del fuzzer)
        params = op.get("parameters", [])
        de_ruta = [p for p in params if p["in"] == "path"]
        de_consulta = [p for p in params if p["in"] == "query"]
        base_ruta = {p["name"]: ("1" if _tipo(p["schema"], spec) == "integer" else "X") for p in de_ruta}
        cuerpo_esq, multipart = None, False
        if "requestBody" in op:
            contenido = op["requestBody"]["content"]
            if "application/json" in contenido:
                cuerpo_esq = contenido["application/json"]["schema"]
                if "$ref" in cuerpo_esq:
                    cuerpo_esq = _resolver(cuerpo_esq["$ref"], spec)
            else:
                multipart = True
        base = _cuerpo_base(cuerpo_esq, spec) if cuerpo_esq else None

        def armar(r=None, q=None, c=None, desc="base", ficheros=None, _ruta=ruta, _base_ruta=base_ruta, _base=base, _metodo=metodo):
            valores = {**_base_ruta, **(r or {})}
            url = re.sub(r"\{(\w+)(?::path)?\}", lambda m: str(valores[m.group(1)]), _ruta)
            return _metodo, url, q or {}, (c if c is not None else _base), ficheros, desc

        yield armar()
        for p in de_ruta:
            for v in PATH_VALORES.get(_tipo(p["schema"], spec), PATH_VALORES["string"]):
                yield armar(r={p["name"]: v}, desc=f"ruta {p['name']}={v[:20]!r}")
        for p in de_consulta:
            for v in MUTACIONES.get(_tipo(p["schema"], spec), MUTACIONES["string"]):
                if isinstance(v, list | dict) or v in (NAN, INF):
                    continue
                yield armar(q={p["name"]: v}, desc=f"consulta {p['name']}={str(v)[:20]!r}")
        if cuerpo_esq:
            for nombre, prop in cuerpo_esq.get("properties", {}).items():
                for v in MUTACIONES.get(_tipo(prop, spec), MUTACIONES["string"]):
                    yield armar(c={**base, nombre: v}, desc=f"cuerpo {nombre}={str(v)[:20]!r}")
            yield armar(c={}, desc="cuerpo vacío")
            yield armar(c=["no", "es", "un", "objeto"], desc="cuerpo lista")
        if multipart:
            for nombre, datos in (("vacio.pdf", b""), ("basura.pdf", b"\x00\xff" * 500), ("../../fuera.pdf", b"%PDF-1.4\n%%EOF"), ("x" * 300 + ".csv", b"a;b\n1;2"), ("stock.csv", b"codigo;stock\n;\nX;1e400\nY;NaN\n")):
                yield armar(ficheros={"fichero": (nombre, datos, "application/octet-stream")}, desc=f"fichero {nombre[:20]!r}")


def test_ninguna_ruta_da_error_500(cliente, admin):
    from hidral_plan.api.app import crear_app

    spec = crear_app().openapi()
    fallos, total = [], 0
    for metodo, url, consulta, cuerpo, ficheros, desc in _peticiones(spec):
        total += 1
        try:
            if ficheros:
                r = cliente.request(metodo.upper(), url, headers=admin, params=consulta, files=ficheros)
            elif cuerpo is not None:
                r = cliente.request(metodo.upper(), url, headers={**admin, "Content-Type": "application/json"}, params=consulta, content=_json(cuerpo).encode())
            else:
                r = cliente.request(metodo.upper(), url, headers=admin, params=consulta)
            if r.status_code >= 500:
                fallos.append(f"{metodo.upper()} {url[:70]} [{desc}] → {r.status_code} {r.text[:160]}")
        except Exception as e:  # excepción no controlada en el servidor
            fallos.append(f"{metodo.upper()} {url[:70]} [{desc}] → {type(e).__name__}: {str(e)[:200]}")
    assert total > 1000
    assert not fallos, f"{len(fallos)} de {total} peticiones fallaron:\n" + "\n".join(dict.fromkeys(fallos))


def test_sin_sesion_nada_responde(cliente, fabrica):
    from hidral_plan.api.app import crear_app

    spec = crear_app().openapi()
    abiertas = []
    for ruta, ops in spec["paths"].items():
        for metodo in ops:
            if ruta in ("/api/auth/login", "/api/salud") or not ruta.startswith("/api/"):
                continue
            url = re.sub(r"\{(\w+)(?::path)?\}", "1", ruta)
            r = cliente.request(metodo.upper(), url)
            if r.status_code not in (401, 422):
                abiertas.append(f"{metodo.upper()} {ruta} → {r.status_code}")
            r = cliente.request(metodo.upper(), url, headers={"Authorization": "Bearer inventado.firma"})
            if r.status_code not in (401, 422):
                abiertas.append(f"{metodo.upper()} {ruta} con token falso → {r.status_code}")
    assert not abiertas, "\n".join(abiertas)


def test_si_falla_al_grabar_no_se_responde_ok(fabrica):
    """El commit ocurre antes de responder: un error al grabar llega como error, no como un 200
    de algo que no se ha guardado."""
    from fastapi import Depends
    from fastapi.testclient import TestClient
    from sqlalchemy import func, select

    from hidral_plan.api.app import crear_app
    from hidral_plan.api.deps import get_sesion
    from hidral_plan.db import sesion
    from hidral_plan.modelos import Usuario

    app = crear_app()

    @app.post("/api/prueba-duplicado")
    def duplicado(s=Depends(get_sesion, scope="function")) -> dict:
        s.add(Usuario(usuario="admin", nombre="copia", rol="CONSULTA", hash_clave="x"))  # choca al grabar
        return {"ok": True}

    with TestClient(app) as c:
        r = c.post("/api/prueba-duplicado")
    assert r.status_code == 409, r.text
    with sesion() as s:
        assert s.scalar(select(func.count(Usuario.id)).where(Usuario.usuario == "admin")) == 1


def test_login_no_distingue_usuario_inexistente_por_tiempo(cliente, fabrica):
    import time

    def medir(usuario: str) -> float:
        t0 = time.perf_counter()
        cliente.post("/api/auth/login", json={"usuario": usuario, "clave": "mala-clave"})
        return time.perf_counter() - t0

    existe = min(medir("planificador") for _ in range(3))
    no_existe = min(medir(f"nadie{i}") for i in range(3))
    # sin la verificación simulada, un usuario inexistente respondía varias veces más rápido
    assert no_existe > existe * 0.5


def test_dos_peticiones_a_la_vez_no_dejan_datos_imposibles(fabrica):
    """Lo comprobado en el código no basta si llegan dos peticiones juntas: la base de datos lo
    garantiza (un trabajo abierto por operario, un plan oficial activo)."""
    from datetime import datetime

    from sqlalchemy.exc import IntegrityError

    from hidral_plan.db import fabrica_sesiones
    from hidral_plan.modelos import Fichaje, Operacion, Operario, OrdenFabricacion, Plan, Tanda

    F = fabrica_sesiones()
    with F() as s:
        t = Tanda(numero="T1", estado="ACTIVA")
        s.add(t)
        s.flush()
        of = OrdenFabricacion(numero="1", tanda_id=t.id)
        s.add(of)
        s.flush()
        op = Operacion(of_id=of.id, tipo="MONTAJE")
        s.add(op)
        s.flush()
        oid, of_id, op_id = s.get(Operario, 1).id, of.id, op.id
        s.commit()
    a, b = F(), F()
    for x in (a, b):
        x.add(Fichaje(operario_id=oid, of_id=of_id, operacion_id=op_id, inicio=datetime(2026, 9, 21, 8), estado="ABIERTO"))
    a.commit()
    with pytest.raises(IntegrityError):
        b.commit()
    b.rollback()
    for x in (a, b):
        x.add(Plan(nombre="p", tipo="OFICIAL", estado="ACTIVO", ahora_referencia=datetime(2026, 9, 21)))
    a.commit()
    with pytest.raises(IntegrityError):
        b.commit()
    a.close()
    b.close()


def _pdf_cifrado(ruta):
    import pymupdf

    d = pymupdf.open()
    d.new_page().insert_text((72, 72), "TANDA 5555")
    d.save(ruta, encryption=pymupdf.PDF_ENCRYPT_AES_256, user_pw="abc", owner_pw="xyz")
    d.close()


def _pdf_paginas_en_blanco(ruta, n):
    import pymupdf

    d = pymupdf.open()
    for _ in range(n):
        d.new_page()
    d.save(ruta)
    d.close()


@pytest.mark.parametrize("caso", ["cifrado", "cero", "truncado", "no_es_pdf", "en_blanco"])
def test_pdf_hostiles_no_rompen_nada(cliente, fabrica, caso):
    """Un PDF cifrado, vacío, cortado, falso o sin texto termina con un estado claro (error o
    completado sin datos), nunca con un fallo del servidor ni un trabajo colgado."""
    from hidral_plan.ingesta.cola import reclamar_trabajo
    from hidral_plan.ingesta.pipeline import procesar_trabajo

    h = {"Authorization": f"Bearer {cliente.post('/api/auth/login', json={'usuario': 'planificador', 'clave': 'hidral'}).json()['token']}"}
    ruta = fabrica / f"{caso}.pdf"
    if caso == "cifrado":
        _pdf_cifrado(ruta)
    elif caso == "cero":
        ruta.write_bytes(b"%PDF-1.4\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n2 0 obj<</Type/Pages/Kids[]/Count 0>>endobj\ntrailer<</Root 1 0 R>>\n%%EOF")
    elif caso == "truncado":
        _pdf_paginas_en_blanco(ruta, 50)
        datos = ruta.read_bytes()
        ruta.write_bytes(datos[: len(datos) // 3])
    elif caso == "no_es_pdf":
        ruta.write_bytes(b"MZ\x90\x00" + b"\x00" * 2000)  # un ejecutable con extensión .pdf
    else:
        _pdf_paginas_en_blanco(ruta, 40)
    r = cliente.post("/api/documentos", headers=h, files={"fichero": (ruta.name, ruta.read_bytes(), "application/pdf")})
    assert r.status_code in (202, 400, 413), r.text
    if r.status_code == 202 and r.json().get("trabajo_id"):
        trabajo = reclamar_trabajo("test")
        if trabajo:
            procesar_trabajo(trabajo)
        t = cliente.get(f"/api/trabajos/{r.json()['trabajo_id']}", headers=h).json()
        assert t["estado"] in ("COMPLETADO", "ERROR", "CANCELADO"), t
        d = cliente.get(f"/api/documentos/{r.json()['documento_id']}", headers=h)
        assert d.status_code == 200
        if t["estado"] == "ERROR":
            assert t["error"]
    # la aplicación sigue funcionando
    assert cliente.get("/api/tandas", headers=h).status_code == 200
    assert cliente.post("/api/plan/generar", headers=h, json={}).status_code == 200


def test_pdf_con_demasiadas_paginas_se_rechaza(cliente, fabrica, monkeypatch):
    from hidral_plan.config import ajustes

    monkeypatch.setattr(ajustes(), "max_paginas", 10)
    h = {"Authorization": f"Bearer {cliente.post('/api/auth/login', json={'usuario': 'planificador', 'clave': 'hidral'}).json()['token']}"}
    ruta = fabrica / "largo.pdf"
    _pdf_paginas_en_blanco(ruta, 11)
    r = cliente.post("/api/documentos", headers=h, files={"fichero": ("largo.pdf", ruta.read_bytes(), "application/pdf")}).json()
    assert r["trabajo_id"] is None and "máximo es 10" in r["mensaje"]
    assert cliente.get(f"/api/documentos/{r['documento_id']}", headers=h).json()["estado"] == "ERROR"


def test_peticion_demasiado_grande_se_corta(cliente, fabrica, monkeypatch):
    from hidral_plan.config import ajustes

    monkeypatch.setattr(ajustes(), "max_pdf_mb", 1)
    monkeypatch.setattr(ajustes(), "max_csv_mb", 1)
    h = {"Authorization": f"Bearer {cliente.post('/api/auth/login', json={'usuario': 'planificador', 'clave': 'hidral'}).json()['token']}"}
    grande = b"%PDF-1.4\n" + b"0" * (3 * 1024 * 1024)
    r = cliente.post("/api/documentos", headers=h, files={"fichero": ("grande.pdf", grande, "application/pdf")})
    assert r.status_code == 413 and "tamaño máximo" in r.json()["detail"]
    # sin Content-Length (envío por trozos) también se corta
    trozos = (b"x" * 65536 for _ in range(60))
    r = cliente.post("/api/documentos", headers={**h, "content-type": "multipart/form-data; boundary=b"}, content=trozos)
    assert r.status_code == 413
    r = cliente.post("/api/auth/login", headers={"content-length": "-1", "content-type": "application/json"}, content=b"{}")
    assert r.status_code in (400, 413)
    assert cliente.get("/api/documentos", headers=h).json() == []
    # lo normal sigue entrando
    assert cliente.post("/api/auth/login", json={"usuario": "planificador", "clave": "hidral"}).status_code == 200
