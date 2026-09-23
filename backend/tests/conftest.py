from __future__ import annotations

import os
import shutil
from datetime import datetime
from pathlib import Path

import pytest
import yaml

from hidral_plan.config import reiniciar_ajustes
from hidral_plan.db import Base, crear_tablas, motor, reiniciar_motor, sesion

RAIZ = Path(__file__).resolve().parent.parent
AHORA = datetime(2026, 9, 21, 7, 0)  # lunes de la semana 39: la semana objetivo 202640 vence el viernes 02/10
PDF_REAL = Path(os.environ.get("HIDRAL_PDF_EJEMPLO", RAIZ / "tests" / "fixtures" / "07_Tanda_EH-2210_OrdenesFab.pdf"))


# Para ejecutar la batería contra PostgreSQL: HIDRAL_TEST_DB_URL=postgresql+psycopg://usuario@host/bd_pruebas
# (¡la base se vacía en cada test!). Por defecto, SQLite en un directorio temporal.
URL_BD_PRUEBAS = os.environ.get("HIDRAL_TEST_DB_URL")


@pytest.fixture()
def entorno(tmp_path, monkeypatch):
    monkeypatch.setenv("HIDRAL_DB_URL", URL_BD_PRUEBAS or f"sqlite:///{tmp_path / 'hidral.db'}")
    monkeypatch.setenv("HIDRAL_ALMACEN_DIR", str(tmp_path / "almacen"))
    monkeypatch.setenv("HIDRAL_WORKER_EN_PROCESO", "0")
    monkeypatch.setenv("HIDRAL_AHORA", AHORA.isoformat())
    monkeypatch.setenv("HIDRAL_BLOQUE_MIN", "5")
    reiniciar_ajustes()
    reiniciar_motor()
    if URL_BD_PRUEBAS:
        Base.metadata.drop_all(motor())
    crear_tablas()
    yield tmp_path
    reiniciar_motor()


@pytest.fixture()
def fabrica(entorno):
    """Configuración de fábrica de EJEMPLO (recursos, turnos, operarios, tiempos)."""
    from hidral_plan.semilla import cargar_configuracion

    with sesion() as s:
        cargar_configuracion(s, yaml.safe_load((RAIZ / "config" / "fabrica_ejemplo.yaml").read_text(encoding="utf-8")), True)
    return entorno


@pytest.fixture()
def importar(entorno):
    """Importa un PDF (copiándolo, porque el almacén mueve el fichero) de forma síncrona."""
    from hidral_plan.ingesta.pipeline import procesar_sincrono

    def _importar(ruta: Path, nombre: str | None = None):
        copia = entorno / f"subida_{ruta.name}"
        shutil.copy(ruta, copia)
        return procesar_sincrono(copia, nombre or ruta.name, "test")

    return _importar


def plan_valido(asignaciones) -> list[str]:
    """Comprobación independiente de las restricciones duras sobre un plan en memoria."""
    errores = []
    por_rec: dict = {}
    por_op: dict = {}
    for a in asignaciones:
        por_rec.setdefault((a.recurso_id, a.unidad), []).extend(a.tramos)
        if a.operario_id is not None:
            por_op.setdefault(a.operario_id, []).extend(a.tramos)
    for clave, tramos in list(por_rec.items()) + list(por_op.items()):
        tramos = sorted(tramos)
        for (a0, a1), (b0, b1) in zip(tramos, tramos[1:], strict=False):
            if b0 < a1:
                errores.append(f"solape en {clave}: {a0}-{a1} / {b0}-{b1}")
    return errores
