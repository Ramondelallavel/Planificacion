"""Planes de producción (oficial y simulaciones), asignaciones y registro de cambios."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..db import Base
from .comun import ahora
from .enums import EstadoPlan, TipoPlan


class Plan(Base):
    __tablename__ = "plan"

    id: Mapped[int] = mapped_column(primary_key=True)
    nombre: Mapped[str] = mapped_column(String(120))
    tipo: Mapped[str] = mapped_column(String(16), default=TipoPlan.OFICIAL, index=True)
    estado: Mapped[str] = mapped_column(String(16), default=EstadoPlan.BORRADOR, index=True)
    creado: Mapped[datetime] = mapped_column(DateTime, default=ahora)
    creado_por: Mapped[str | None] = mapped_column(String(80))
    ahora_referencia: Mapped[datetime] = mapped_column(DateTime)  # instante "ahora" usado al calcular
    horizonte_fin: Mapped[datetime | None] = mapped_column(DateTime)
    configuracion: Mapped[dict | None] = mapped_column(JSON)  # pesos y parámetros usados (reproducibilidad)
    kpis: Mapped[dict | None] = mapped_column(JSON)
    riesgos: Mapped[dict | None] = mapped_column(JSON)  # instantánea de riesgos por tanda/aparato
    no_planificadas: Mapped[list | None] = mapped_column(JSON)  # operaciones excluidas y motivo
    comprobaciones: Mapped[list | None] = mapped_column(JSON)  # resultado de validación previa
    plan_base_id: Mapped[int | None] = mapped_column(ForeignKey("plan.id"))
    escenario: Mapped[dict | None] = mapped_column(JSON)  # simulación: qué se modificó
    motivo: Mapped[str | None] = mapped_column(Text)
    definitivo: Mapped[bool] = mapped_column(Boolean, default=False)

    asignaciones: Mapped[list[AsignacionPlan]] = relationship(back_populates="plan", cascade="all, delete-orphan")


class AsignacionPlan(Base):
    __tablename__ = "asignacion_plan"
    __table_args__ = (
        Index("ix_asig_plan_recurso_inicio", "plan_id", "recurso_id", "inicio"),
        Index("ix_asig_plan_operario_inicio", "plan_id", "operario_id", "inicio"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    plan_id: Mapped[int] = mapped_column(ForeignKey("plan.id", ondelete="CASCADE"), index=True)
    operacion_id: Mapped[int] = mapped_column(ForeignKey("operacion.id", ondelete="CASCADE"), index=True)
    of_id: Mapped[int] = mapped_column(ForeignKey("orden_fabricacion.id", ondelete="CASCADE"), index=True)
    recurso_id: Mapped[int | None] = mapped_column(ForeignKey("recurso.id"), index=True)
    unidad: Mapped[int] = mapped_column(Integer, default=0)  # unidad dentro de un recurso con capacidad > 1
    operario_id: Mapped[int | None] = mapped_column(ForeignKey("operario.id"), index=True)
    inicio: Mapped[datetime] = mapped_column(DateTime, index=True)
    fin: Mapped[datetime] = mapped_column(DateTime, index=True)
    segmentos: Mapped[list | None] = mapped_column(JSON)  # tramos reales de trabajo (se parte en fin de turno)
    minutos: Mapped[float] = mapped_column(Float)
    prioridad: Mapped[float | None] = mapped_column(Float)
    bloqueada: Mapped[bool] = mapped_column(Boolean, default=False)  # fijada por el usuario
    provisional: Mapped[bool] = mapped_column(Boolean, default=False)  # p.ej. pendiente de programa
    explicacion: Mapped[dict | None] = mapped_column(JSON)

    plan: Mapped[Plan] = relationship(back_populates="asignaciones")


class CambioPlan(Base):
    """Registro ANTES / DESPUÉS / MOTIVO / IMPACTO de cada cambio en un plan (punto 20)."""

    __tablename__ = "cambio_plan"

    id: Mapped[int] = mapped_column(primary_key=True)
    plan_id: Mapped[int] = mapped_column(ForeignKey("plan.id", ondelete="CASCADE"), index=True)
    lote: Mapped[str] = mapped_column(String(40), index=True)  # agrupa los cambios de un mismo evento
    fecha: Mapped[datetime] = mapped_column(DateTime, default=ahora, index=True)
    usuario: Mapped[str | None] = mapped_column(String(80))
    tipo: Mapped[str] = mapped_column(String(24))  # REPLANIFICACION | MANUAL | OF_URGENTE | GENERACION
    operacion_id: Mapped[int | None] = mapped_column(ForeignKey("operacion.id", ondelete="SET NULL"))
    of_numero: Mapped[str | None] = mapped_column(String(16), index=True)
    antes: Mapped[dict | None] = mapped_column(JSON)
    despues: Mapped[dict | None] = mapped_column(JSON)
    impacto_min: Mapped[float | None] = mapped_column(Float)
    motivo: Mapped[str | None] = mapped_column(Text)
    riesgo_antes: Mapped[str | None] = mapped_column(String(12))
    riesgo_despues: Mapped[str | None] = mapped_column(String(12))
