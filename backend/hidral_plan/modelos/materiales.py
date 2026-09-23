"""Materiales: stock y entradas previstas de los artículos que consumen las OF.

Solo se controlan los materiales dados de alta aquí; los demás se consideran fuera del
control de la aplicación (su disponibilidad la dice el MRP o una persona en la OF).
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..db import Base
from .comun import ahora


class Material(Base):
    __tablename__ = "material"

    codigo: Mapped[str] = mapped_column(String(40), primary_key=True)  # código de artículo, p.ej. "1202114/1"
    descripcion: Mapped[str | None] = mapped_column(String(240))
    unidad: Mapped[str] = mapped_column(String(16), default="ud")
    stock: Mapped[float] = mapped_column(Float, default=0.0)
    controlado: Mapped[bool] = mapped_column(Boolean, default=True)
    plazo_dias: Mapped[int | None] = mapped_column(Integer)  # reposición si falta y no hay entrada prevista
    notas: Mapped[str | None] = mapped_column(Text)
    actualizado: Mapped[datetime] = mapped_column(DateTime, default=ahora)
    actualizado_por: Mapped[str | None] = mapped_column(String(80))

    entradas: Mapped[list[EntradaMaterial]] = relationship(back_populates="material", cascade="all, delete-orphan", order_by="EntradaMaterial.fecha_prevista")


class EntradaMaterial(Base):
    """Pedido o recepción prevista de material."""

    __tablename__ = "entrada_material"

    id: Mapped[int] = mapped_column(primary_key=True)
    material_codigo: Mapped[str] = mapped_column(ForeignKey("material.codigo", ondelete="CASCADE"), index=True)
    cantidad: Mapped[float] = mapped_column(Float)
    fecha_prevista: Mapped[datetime] = mapped_column(DateTime, index=True)
    recibida: Mapped[bool] = mapped_column(Boolean, default=False)
    recibida_en: Mapped[datetime | None] = mapped_column(DateTime)
    referencia: Mapped[str | None] = mapped_column(String(80))  # pedido, proveedor…
    creado_por: Mapped[str | None] = mapped_column(String(80))
    creado: Mapped[datetime] = mapped_column(DateTime, default=ahora)

    material: Mapped[Material] = relationship(back_populates="entradas")
