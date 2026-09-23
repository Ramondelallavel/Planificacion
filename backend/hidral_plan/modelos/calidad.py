"""Calidad y trazabilidad de datos: incidencias de datos ("REVISIÓN NECESARIA") y origen de cada dato."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from ..db import Base
from .comun import ahora
from .enums import EstadoIncidenciaDatos


class IncidenciaDatos(Base):
    __tablename__ = "incidencia_datos"
    __table_args__ = (Index("ix_incdatos_doc_sev", "documento_id", "severidad"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    documento_id: Mapped[int | None] = mapped_column(ForeignKey("documento.id", ondelete="CASCADE"), index=True)
    pagina: Mapped[int | None] = mapped_column(Integer)
    tipo: Mapped[str] = mapped_column(String(40), index=True)
    severidad: Mapped[str] = mapped_column(String(12), index=True)
    mensaje: Mapped[str] = mapped_column(Text)
    entidad_tipo: Mapped[str | None] = mapped_column(String(24))
    entidad_ref: Mapped[str | None] = mapped_column(String(64), index=True)
    texto_origen: Mapped[str | None] = mapped_column(Text)
    alternativas: Mapped[list | None] = mapped_column(JSON)  # ambigüedad: posibles interpretaciones
    estado: Mapped[str] = mapped_column(String(12), default=EstadoIncidenciaDatos.ABIERTA, index=True)
    creada: Mapped[datetime] = mapped_column(DateTime, default=ahora)
    resuelta_por: Mapped[str | None] = mapped_column(String(80))
    resolucion: Mapped[str | None] = mapped_column(Text)


class Origen(Base):
    """De dónde procede cada dato importante: fuente + documento + página + bloque + texto."""

    __tablename__ = "origen"
    __table_args__ = (Index("ix_origen_entidad", "entidad_tipo", "entidad_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    entidad_tipo: Mapped[str] = mapped_column(String(24))
    entidad_id: Mapped[int] = mapped_column(Integer)
    campo: Mapped[str | None] = mapped_column(String(40))
    fuente: Mapped[str] = mapped_column(String(20))
    documento_id: Mapped[int | None] = mapped_column(ForeignKey("documento.id", ondelete="CASCADE"), index=True)
    pagina: Mapped[int | None] = mapped_column(Integer)
    bloque: Mapped[int | None] = mapped_column(Integer)
    texto_origen: Mapped[str | None] = mapped_column(Text)
    detalle: Mapped[str | None] = mapped_column(String(240))
    fecha: Mapped[datetime] = mapped_column(DateTime, default=ahora)
