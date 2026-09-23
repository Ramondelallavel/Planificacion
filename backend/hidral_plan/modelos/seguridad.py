"""Usuarios, auditoría y parámetros de configuración versionados."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from ..db import Base
from .comun import ahora


class Usuario(Base):
    __tablename__ = "usuario"

    id: Mapped[int] = mapped_column(primary_key=True)
    usuario: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    nombre: Mapped[str] = mapped_column(String(120))
    rol: Mapped[str] = mapped_column(String(24))
    hash_clave: Mapped[str] = mapped_column(String(256))
    activo: Mapped[bool] = mapped_column(Boolean, default=True)
    operario_id: Mapped[int | None] = mapped_column(ForeignKey("operario.id"))
    creado: Mapped[datetime] = mapped_column(DateTime, default=ahora)


class Auditoria(Base):
    """Registro inmutable de acciones: importaciones, cambios manuales, replanificaciones,
    decisiones automáticas, cambios de configuración... (punto 53)."""

    __tablename__ = "auditoria"

    id: Mapped[int] = mapped_column(primary_key=True)
    fecha: Mapped[datetime] = mapped_column(DateTime, default=ahora, index=True)
    usuario: Mapped[str] = mapped_column(String(80), index=True)
    accion: Mapped[str] = mapped_column(String(48), index=True)
    entidad_tipo: Mapped[str | None] = mapped_column(String(32), index=True)
    entidad_id: Mapped[str | None] = mapped_column(String(64), index=True)
    antes: Mapped[dict | None] = mapped_column(JSON)
    despues: Mapped[dict | None] = mapped_column(JSON)
    motivo: Mapped[str | None] = mapped_column(Text)
    automatica: Mapped[bool] = mapped_column(Boolean, default=False)


class ParametroConfig(Base):
    """Parámetros de negocio configurables (pesos de prioridad, umbrales de riesgo...)."""

    __tablename__ = "parametro_config"

    clave: Mapped[str] = mapped_column(String(64), primary_key=True)
    valor: Mapped[dict] = mapped_column(JSON)
    version: Mapped[int] = mapped_column(Integer, default=1)
    actualizado: Mapped[datetime] = mapped_column(DateTime, default=ahora)
    actualizado_por: Mapped[str | None] = mapped_column(String(80))
    descripcion: Mapped[str | None] = mapped_column(Text)
