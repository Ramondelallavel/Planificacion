"""Ejecución en planta: fichajes, incidencias de producción, avisos y aprendizaje de tiempos."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from ..db import Base
from .comun import ahora


class Fichaje(Base):
    __tablename__ = "fichaje"

    id: Mapped[int] = mapped_column(primary_key=True)
    operario_id: Mapped[int] = mapped_column(ForeignKey("operario.id"), index=True)
    of_id: Mapped[int] = mapped_column(ForeignKey("orden_fabricacion.id"), index=True)
    operacion_id: Mapped[int] = mapped_column(ForeignKey("operacion.id"), index=True)
    recurso_id: Mapped[int | None] = mapped_column(ForeignKey("recurso.id"), index=True)
    inicio: Mapped[datetime] = mapped_column(DateTime, index=True)
    fin: Mapped[datetime | None] = mapped_column(DateTime)
    pausas: Mapped[list | None] = mapped_column(JSON)  # [{"inicio": iso, "fin": iso|None, "motivo": str}]
    minutos_pausa: Mapped[float] = mapped_column(Float, default=0.0)
    duracion_real_min: Mapped[float | None] = mapped_column(Float)
    duracion_planificada_min: Mapped[float | None] = mapped_column(Float)
    cantidad: Mapped[float | None] = mapped_column(Float)
    estado: Mapped[str] = mapped_column(String(16), default="ABIERTO", index=True)  # ABIERTO | PAUSADO | CERRADO
    incidencia_id: Mapped[int | None] = mapped_column(ForeignKey("incidencia_produccion.id"))
    forzado_por: Mapped[str | None] = mapped_column(String(80))  # supervisor que autorizó una excepción


class IncidenciaProduccion(Base):
    __tablename__ = "incidencia_produccion"

    id: Mapped[int] = mapped_column(primary_key=True)
    tipo: Mapped[str] = mapped_column(String(24), index=True)
    descripcion: Mapped[str] = mapped_column(Text)
    recurso_id: Mapped[int | None] = mapped_column(ForeignKey("recurso.id"))
    operario_id: Mapped[int | None] = mapped_column(ForeignKey("operario.id"))
    of_id: Mapped[int | None] = mapped_column(ForeignKey("orden_fabricacion.id"))
    operacion_id: Mapped[int | None] = mapped_column(ForeignKey("operacion.id"))
    inicio: Mapped[datetime] = mapped_column(DateTime, default=ahora, index=True)
    fin_prevista: Mapped[datetime | None] = mapped_column(DateTime)
    fin: Mapped[datetime | None] = mapped_column(DateTime)
    estado: Mapped[str] = mapped_column(String(16), default="ABIERTA", index=True)
    severidad: Mapped[str] = mapped_column(String(16), default="MEDIA")
    reportado_por: Mapped[str | None] = mapped_column(String(80))
    lote_replanificacion: Mapped[str | None] = mapped_column(String(40))
    impacto: Mapped[dict | None] = mapped_column(JSON)


class Notificacion(Base):
    """Aviso al personal afectado por un cambio de plan o una incidencia."""

    __tablename__ = "notificacion"

    id: Mapped[int] = mapped_column(primary_key=True)
    fecha: Mapped[datetime] = mapped_column(DateTime, default=ahora, index=True)
    operario_id: Mapped[int | None] = mapped_column(ForeignKey("operario.id"), index=True)
    rol_destino: Mapped[str | None] = mapped_column(String(24))
    titulo: Mapped[str] = mapped_column(String(160))
    mensaje: Mapped[str] = mapped_column(Text)
    nivel: Mapped[str] = mapped_column(String(12), default="INFO")
    leida: Mapped[bool] = mapped_column(Boolean, default=False)
    referencia: Mapped[str | None] = mapped_column(String(80))


class EstimacionPropuesta(Base):
    """Propuesta de nuevo tiempo estándar calculada con históricos. Requiere aprobación humana
    (el aprendizaje es trazable, reversible y explicable)."""

    __tablename__ = "estimacion_propuesta"

    id: Mapped[int] = mapped_column(primary_key=True)
    tiempo_estandar_id: Mapped[int] = mapped_column(ForeignKey("tiempo_estandar.id"), index=True)
    muestras: Mapped[int] = mapped_column(Integer)
    ratio_real_planificado: Mapped[float] = mapped_column(Float)
    minutos_por_unidad_actual: Mapped[float] = mapped_column(Float)
    minutos_por_unidad_propuesto: Mapped[float] = mapped_column(Float)
    explicacion: Mapped[str] = mapped_column(Text)
    estado: Mapped[str] = mapped_column(String(16), default="PROPUESTA", index=True)  # PROPUESTA | APROBADA | RECHAZADA
    creada: Mapped[datetime] = mapped_column(DateTime, default=ahora)
    decidida_por: Mapped[str | None] = mapped_column(String(80))
    decidida: Mapped[datetime | None] = mapped_column(DateTime)
