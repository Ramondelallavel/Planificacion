"""Empaqueta la edición «navegador»: la aplicación completa (interfaz + backend Python) para
ejecutarse sin servidor dentro del navegador, con Pyodide (Python compilado a WebAssembly).

    python herramientas/empaquetar_navegador.py

Resultado en frontend/dist-navegador/:
    index.html            página para servir en local (python -m http.server)
    hidral.html           la misma página como fragmento autocontenido (para publicarla)
    motor/motor.js        Web Worker que ejecuta el backend
    motor/pyodide/…       núcleo de Pyodide (del paquete npm «pyodide»)
    motor/paquetes/…      dependencias Python y el propio backend (hidral_plan)
    motor/paquetes.json   manifiesto que lee el worker

Las ruedas se descargan de PyPI y se comprueban con su SHA-256 publicado. Los ficheros de más de
14 MB se trocean (algunos alojamientos limitan el tamaño por fichero) y el worker los une.
"""

from __future__ import annotations

import hashlib
import io
import json
import re
import shutil
import subprocess
import sys
import tarfile
import urllib.request
import zipfile
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
FRONT = RAIZ / "frontend"
BACK = RAIZ / "backend"
SALIDA = FRONT / "dist-navegador"
CACHE = FRONT / ".cache-navegador"
MAX_TROZO = 14 * 1024 * 1024

# Versiones para Pyodide 314 (Python 3.14). pydantic-core solo tiene rueda WebAssembly desde la
# 2.47, que corresponde a pydantic 2.14 (beta). PyMuPDF publica rueda abi3 para emscripten.
RUEDAS = [
    ("pydantic-core", "2.49.0", "pyemscripten_2026_0_wasm32"),
    ("pydantic", "2.14.0b2", "py3-none-any"),
    ("pymupdf", "1.28.2", "pyemscripten_2025_0_wasm32"),
    ("sqlalchemy", "2.0.48", "py3-none-any"),
    ("fastapi", "0.141.1", "py3-none-any"),
    ("starlette", "1.6.0", "py3-none-any"),
    ("anyio", "4.15.1", "py3-none-any"),
    ("idna", "3.11", "py3-none-any"),
    ("typing-extensions", "4.16.0", "py3-none-any"),
    ("annotated-types", "0.8.0", "py3-none-any"),
    ("typing-inspection", "0.4.4", "py3-none-any"),
    ("python-multipart", "0.0.32", "py3-none-any"),
    ("annotated-doc", "0.0.5", "py3-none-any"),
]
PYYAML = "6.0.3"  # solo su parte en Python puro (sin libyaml)
NUCLEO_PYODIDE = ["pyodide.mjs", "pyodide.asm.mjs", "pyodide.asm.wasm", "python_stdlib.zip", "pyodide-lock.json"]


def descargar_pypi(nombre: str, version: str, etiqueta: str) -> Path:
    meta = json.load(urllib.request.urlopen(f"https://pypi.org/pypi/{nombre}/{version}/json"))
    fichero = next((f for f in meta["urls"] if f["filename"].endswith(".whl") and etiqueta in f["filename"]), None)
    if fichero is None:
        raise SystemExit(f"PyPI no tiene rueda {etiqueta} de {nombre} {version}")
    destino = CACHE / fichero["filename"]
    if not destino.exists():
        print("  descargando", fichero["filename"])
        datos = urllib.request.urlopen(fichero["url"]).read()
        if hashlib.sha256(datos).hexdigest() != fichero["digests"]["sha256"]:
            raise SystemExit(f"SHA-256 incorrecto en {fichero['filename']}")
        destino.write_bytes(datos)
    return destino


def yaml_puro() -> Path:
    destino = CACHE / f"pyyaml-{PYYAML}-puro.zip"
    if destino.exists():
        return destino
    meta = json.load(urllib.request.urlopen(f"https://pypi.org/pypi/PyYAML/{PYYAML}/json"))
    sdist = next(f for f in meta["urls"] if f["filename"].endswith(".tar.gz"))
    datos = urllib.request.urlopen(sdist["url"]).read()
    if hashlib.sha256(datos).hexdigest() != sdist["digests"]["sha256"]:
        raise SystemExit("SHA-256 incorrecto en PyYAML")
    with tarfile.open(fileobj=io.BytesIO(datos)) as t, zipfile.ZipFile(destino, "w", zipfile.ZIP_DEFLATED) as z:
        for m in t.getmembers():
            if "/lib/yaml/" in m.name and m.name.endswith(".py"):
                z.writestr("yaml/" + m.name.split("/lib/yaml/")[1], t.extractfile(m).read())
    return destino


def zip_backend() -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for f in sorted((BACK / "hidral_plan").rglob("*.py")):
            z.write(f, f.relative_to(BACK))
    return buf.getvalue()


def tanda_ejemplo(destino: Path) -> None:
    """PDF con la maquetación de las hojas HIDRAL y datos ficticios (el generador de las pruebas)."""
    sys.path.insert(0, str(BACK))
    from tests.generador_pdf import Aparato, OpcionesTanda, generar_tanda

    from datetime import date, timedelta

    hoy = date.today()
    semana = (hoy + timedelta(days=7)).isocalendar().week  # se fabrica la semana que viene
    aparatos = [Aparato("40001", semana=semana), Aparato("40002", semana=semana), Aparato("40003", semana=semana, tipo="EH")]
    generar_tanda(destino, OpcionesTanda(tanda="9001", emision=hoy - timedelta(days=2), aparatos=aparatos))


def trocear(datos: bytes, carpeta: Path, nombre: str) -> list[str]:
    if len(datos) <= MAX_TROZO:
        (carpeta / nombre).write_bytes(datos)
        return [f"paquetes/{nombre}"]
    partes = []
    for i in range(0, len(datos), MAX_TROZO):
        parte = f"{nombre}.parte{i // MAX_TROZO}.bin"
        (carpeta / parte).write_bytes(datos[i : i + MAX_TROZO])
        partes.append(f"paquetes/{parte}")
    return partes


def pagina_autocontenida(indice: str) -> str:
    """index.html de Vite → fragmento con el CSS y el JS de la interfaz en línea."""
    titulo = re.search(r"<title>.*?</title>", indice, re.S).group(0)
    css = "".join((SALIDA / m).read_text() for m in re.findall(r'<link rel="stylesheet"[^>]*href="\./([^"]+)"', indice))
    js = "".join((SALIDA / m).read_text() for m in re.findall(r'<script type="module"[^>]*src="\./([^"]+)"', indice))
    js = js.replace("</script", "<\\/script")
    return f'{titulo}\n<meta name="theme-color" content="#0f1b2d">\n<style>{css}</style>\n<div id="root"></div>\n<script type="module">{js}</script>\n'


def main() -> None:
    CACHE.mkdir(exist_ok=True)
    print("1/5 interfaz (vite build, edición navegador)")
    if SALIDA.exists():
        shutil.rmtree(SALIDA)
    subprocess.run(["npx", "tsc", "-b"], cwd=FRONT, check=True)
    subprocess.run(["npx", "vite", "build", "--base", "./", "--outDir", str(SALIDA)], cwd=FRONT, check=True, env={**__import__("os").environ, "VITE_NAVEGADOR": "1"})

    print("2/5 núcleo de Pyodide")
    motor = SALIDA / "motor"
    (motor / "pyodide").mkdir(parents=True)
    (motor / "paquetes").mkdir()
    for f in NUCLEO_PYODIDE:
        shutil.copy(FRONT / "node_modules" / "pyodide" / f, motor / "pyodide" / f)
    shutil.copy(FRONT / "navegador" / "motor.js", motor / "motor.js")

    print("3/5 dependencias Python")
    paquetes = []
    for nombre, version, etiqueta in RUEDAS:
        rueda = descargar_pypi(nombre, version, etiqueta)
        datos = rueda.read_bytes()
        # «.whl» no es un tipo web estándar: se publica como .zip; el worker lo instala como rueda
        paquetes.append({"nombre": nombre, "tipo": "wheel", "bytes": len(datos), "partes": trocear(datos, motor / "paquetes", rueda.stem + ".zip")})
    datos = yaml_puro().read_bytes()
    paquetes.append({"nombre": "pyyaml", "tipo": "zip", "destino": "/lib/python3.14/site-packages", "bytes": len(datos), "partes": trocear(datos, motor / "paquetes", "pyyaml-puro.zip")})

    print("4/5 backend HIDRAL, configuración y tanda de ejemplo")
    datos = zip_backend()
    paquetes.append({"nombre": "hidral_plan", "tipo": "zip", "destino": "/app", "bytes": len(datos), "partes": trocear(datos, motor / "paquetes", "hidral_plan.zip")})
    shutil.copy(BACK / "config" / "fabrica_ejemplo.yaml", motor / "fabrica_ejemplo.txt")
    tanda_ejemplo(motor / "TANDA_EJEMPLO_9001.pdf")
    (motor / "paquetes.json").write_text(
        json.dumps({"paquetes": paquetes, "config": "fabrica_ejemplo.txt", "ejemplo": "TANDA_EJEMPLO_9001.pdf"}, indent=1, ensure_ascii=False)
    )

    print("5/5 página autocontenida")
    indice = (SALIDA / "index.html").read_text()
    (SALIDA / "hidral.html").write_text(pagina_autocontenida(indice))
    total = sum(f.stat().st_size for f in SALIDA.rglob("*") if f.is_file())
    grandes = [f for f in motor.rglob("*") if f.is_file() and f.stat().st_size > 15 * 1024 * 1024]
    print(f"Listo: {SALIDA} · {total / 1048576:.1f} MB · {sum(1 for f in motor.rglob('*') if f.is_file())} ficheros de motor")
    if grandes:
        raise SystemExit(f"Ficheros de más de 15 MB: {grandes}")


if __name__ == "__main__":
    main()
