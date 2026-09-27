"""Conexión a la base de datos relacional (PostgreSQL en producción, SQLite en desarrollo)."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from .config import ajustes


class Base(DeclarativeBase):
    pass


_engine: Engine | None = None
_SessionLocal: sessionmaker[Session] | None = None


def _configurar_sqlite(dbapi_conn, _record) -> None:
    cur = dbapi_conn.cursor()
    cur.execute("PRAGMA foreign_keys=ON")
    diario = ajustes().sqlite_diario
    cur.execute(f"PRAGMA journal_mode={diario if diario in ('WAL', 'DELETE', 'TRUNCATE', 'MEMORY') else 'WAL'}")
    cur.execute("PRAGMA busy_timeout=10000")
    cur.close()


def motor() -> Engine:
    global _engine, _SessionLocal
    if _engine is None:
        url = ajustes().db_url
        kwargs: dict = {"future": True}
        if url.startswith("sqlite"):
            ruta = url.split("sqlite:///", 1)[-1]
            if ruta and ruta != ":memory:":
                Path(ruta).parent.mkdir(parents=True, exist_ok=True)
            kwargs["connect_args"] = {"check_same_thread": False, "timeout": 30}
        else:
            kwargs["pool_pre_ping"] = True
            kwargs["pool_size"] = 10
        _engine = create_engine(url, **kwargs)
        if url.startswith("sqlite"):
            event.listen(_engine, "connect", _configurar_sqlite)
        _SessionLocal = sessionmaker(bind=_engine, expire_on_commit=False, autoflush=False)
    return _engine


def fabrica_sesiones() -> sessionmaker[Session]:
    motor()
    assert _SessionLocal is not None
    return _SessionLocal


@contextmanager
def sesion() -> Iterator[Session]:
    s = fabrica_sesiones()()
    try:
        yield s
        s.commit()
    except Exception:
        s.rollback()
        raise
    finally:
        s.close()


def es_postgres() -> bool:
    return motor().dialect.name == "postgresql"


def crear_tablas() -> None:
    from . import modelos  # noqa: F401  (registra los modelos en Base.metadata)

    Base.metadata.create_all(motor())
    migrar_columnas()


def _literal(valor, dialecto: str) -> str | None:
    if isinstance(valor, bool):
        return ("TRUE" if valor else "FALSE") if dialecto == "postgresql" else ("1" if valor else "0")
    if isinstance(valor, int | float):
        return str(valor)
    if isinstance(valor, str):
        return "'" + valor.replace("'", "''") + "'"
    return None


def migrar_columnas() -> list[str]:
    """create_all crea las tablas nuevas pero no añade columnas nuevas a las que ya existen. Con
    esto una base creada por una versión anterior (la del navegador de cada usuario, o una
    instalación con datos) sigue funcionando: se añaden las columnas que falten."""
    from sqlalchemy import inspect, text

    eng = motor()
    insp = inspect(eng)
    hechas: list[str] = []
    with eng.begin() as con:
        for tabla in Base.metadata.sorted_tables:
            if not insp.has_table(tabla.name):
                continue
            existentes = {c["name"] for c in insp.get_columns(tabla.name)}
            for col in tabla.columns:
                if col.name in existentes:
                    continue
                tipo = col.type.compile(dialect=eng.dialect)
                defecto = col.default.arg if col.default is not None and getattr(col.default, "is_scalar", False) else None
                lit = _literal(defecto, eng.dialect.name) if defecto is not None else None
                con.execute(text(f'ALTER TABLE "{tabla.name}" ADD COLUMN "{col.name}" {tipo}' + (f" DEFAULT {lit}" if lit else "")))
                hechas.append(f"{tabla.name}.{col.name}")
    # índices nuevos (p.ej. los únicos que impiden dobles fichajes o dos planes activos)
    import logging

    log = logging.getLogger(__name__)
    insp = inspect(eng)
    for tabla in Base.metadata.sorted_tables:
        if not insp.has_table(tabla.name):
            continue
        existentes = {i["name"] for i in insp.get_indexes(tabla.name)}
        for indice in tabla.indexes:
            if indice.name and indice.name not in existentes:
                try:
                    indice.create(eng)
                    hechas.append(f"índice {indice.name}")
                except Exception as e:  # datos antiguos que lo incumplen: se avisa y se sigue
                    log.error("No se pudo crear el índice %s: %s", indice.name, e)
    if hechas:
        log.warning("Esquema actualizado: %s", ", ".join(hechas))
    return hechas


def reiniciar_motor() -> None:
    """Descarta el motor (tests)."""
    global _engine, _SessionLocal
    if _engine is not None:
        _engine.dispose()
    _engine = None
    _SessionLocal = None
