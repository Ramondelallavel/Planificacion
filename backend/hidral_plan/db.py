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


def reiniciar_motor() -> None:
    """Descarta el motor (tests)."""
    global _engine, _SessionLocal
    if _engine is not None:
        _engine.dispose()
    _engine = None
    _SessionLocal = None
