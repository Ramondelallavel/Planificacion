"""Recursos productivos, personal, turnos y tiempos estándar (configuración de fábrica)."""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import JSON, Boolean, Date, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..db import Base
from .comun import ahora
from .enums import EstadoRecurso, Fuente


class Seccion(Base):
    __tablename__ = "seccion"

    codigo: Mapped[str] = mapped_column(String(32), primary_key=True)  # "MF"
    codigo_completo: Mapped[str | None] = mapped_column(String(40))  # "SC000003-MF"
    nombre: Mapped[str | None] = mapped_column(String(120))  # None = DATO NO DISPONIBLE
    flujo: Mapped[str] = mapped_column(String(24), default="NORMAL")  # NORMAL | LCH | LASERTUB | PINTURA...
    requiere_programacion: Mapped[bool] = mapped_column(Boolean, default=False)
    conocida: Mapped[bool] = mapped_column(Boolean, default=True)  # False = detectada en PDF y no configurada
    fuente: Mapped[str] = mapped_column(String(20), default=Fuente.CONFIG_FABRICA)


class Recurso(Base):
    __tablename__ = "recurso"

    id: Mapped[int] = mapped_column(primary_key=True)
    codigo: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    nombre: Mapped[str] = mapped_column(String(120))
    tipo: Mapped[str] = mapped_column(String(16))
    seccion_codigo: Mapped[str | None] = mapped_column(ForeignKey("seccion.codigo"), index=True)
    capacidad: Mapped[int] = mapped_column(Integer, default=1)  # unidades en paralelo
    estado: Mapped[str] = mapped_column(String(16), default=EstadoRecurso.OPERATIVO, index=True)
    operaciones: Mapped[list | None] = mapped_column(JSON)  # tipos de operación que puede hacer
    alias: Mapped[list | None] = mapped_column(JSON)  # palabras clave en títulos de programa (p.ej. LASERTUB)
    grupos_hf: Mapped[list | None] = mapped_column(JSON)  # restricción opcional a Grupos HF concretos
    turnos: Mapped[list | None] = mapped_column(JSON)  # códigos de turno en que trabaja
    requiere_operario: Mapped[bool] = mapped_column(Boolean, default=True)
    restricciones: Mapped[dict | None] = mapped_column(JSON)  # p.ej. {"espesor_max_mm": 12, "largo_max_mm": 6500}
    activo: Mapped[bool] = mapped_column(Boolean, default=True)
    fuente: Mapped[str] = mapped_column(String(20), default=Fuente.CONFIG_FABRICA)


class ParadaRecurso(Base):
    """Ventana de indisponibilidad de un recurso (avería, mantenimiento)."""

    __tablename__ = "parada_recurso"

    id: Mapped[int] = mapped_column(primary_key=True)
    recurso_id: Mapped[int] = mapped_column(ForeignKey("recurso.id", ondelete="CASCADE"), index=True)
    inicio: Mapped[datetime] = mapped_column(DateTime, index=True)
    fin: Mapped[datetime | None] = mapped_column(DateTime)  # None = indefinida
    motivo: Mapped[str] = mapped_column(String(200))
    incidencia_id: Mapped[int | None] = mapped_column(ForeignKey("incidencia_produccion.id"))


class Turno(Base):
    __tablename__ = "turno"

    codigo: Mapped[str] = mapped_column(String(8), primary_key=True)  # "M", "T", "N"
    nombre: Mapped[str] = mapped_column(String(60))
    hora_inicio: Mapped[str] = mapped_column(String(5))  # "07:00"
    hora_fin: Mapped[str] = mapped_column(String(5))  # "15:00" (si fin < inicio cruza medianoche)
    dias_semana: Mapped[list] = mapped_column(JSON)  # [0..6] lunes=0
    pausas: Mapped[list | None] = mapped_column(JSON)  # [{"inicio": "10:00", "fin": "10:20"}]
    activo: Mapped[bool] = mapped_column(Boolean, default=True)


class Festivo(Base):
    __tablename__ = "festivo"

    fecha: Mapped[date] = mapped_column(Date, primary_key=True)
    descripcion: Mapped[str | None] = mapped_column(String(120))


class Operario(Base):
    __tablename__ = "operario"

    id: Mapped[int] = mapped_column(primary_key=True)
    codigo_empleado: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    nombre: Mapped[str] = mapped_column(String(120))
    turno_codigo: Mapped[str | None] = mapped_column(ForeignKey("turno.codigo"))
    seccion_codigo: Mapped[str | None] = mapped_column(String(32))
    activo: Mapped[bool] = mapped_column(Boolean, default=True)

    cualificaciones: Mapped[list[Cualificacion]] = relationship(back_populates="operario", cascade="all, delete-orphan")


class Cualificacion(Base):
    """Qué puede hacer un operario: un recurso concreto y/o un tipo de operación."""

    __tablename__ = "cualificacion"

    id: Mapped[int] = mapped_column(primary_key=True)
    operario_id: Mapped[int] = mapped_column(ForeignKey("operario.id", ondelete="CASCADE"), index=True)
    recurso_codigo: Mapped[str | None] = mapped_column(String(64))
    tipo_operacion: Mapped[str | None] = mapped_column(String(32))
    nivel: Mapped[int] = mapped_column(Integer, default=2)  # 1 aprendiz, 2 autónomo, 3 experto/formador
    vigente_hasta: Mapped[date | None] = mapped_column(Date)

    operario: Mapped[Operario] = relationship(back_populates="cualificaciones")


class Ausencia(Base):
    __tablename__ = "ausencia"

    id: Mapped[int] = mapped_column(primary_key=True)
    operario_id: Mapped[int] = mapped_column(ForeignKey("operario.id", ondelete="CASCADE"), index=True)
    inicio: Mapped[datetime] = mapped_column(DateTime, index=True)
    fin: Mapped[datetime | None] = mapped_column(DateTime)
    motivo: Mapped[str] = mapped_column(String(120))
    incidencia_id: Mapped[int | None] = mapped_column(ForeignKey("incidencia_produccion.id"))


class TiempoEstandar(Base):
    """Tiempo estándar por sección / grupo HF / artículo. Versionado: nunca se sobreescribe,
    se crea una versión nueva y la anterior queda como histórico (reversible)."""

    __tablename__ = "tiempo_estandar"

    id: Mapped[int] = mapped_column(primary_key=True)
    seccion_codigo: Mapped[str] = mapped_column(String(32), index=True)
    grupo_hf: Mapped[str | None] = mapped_column(String(120))  # None = cualquier grupo de la sección
    articulo_codigo: Mapped[str | None] = mapped_column(String(40))
    tipo_operacion: Mapped[str | None] = mapped_column(String(32))
    minutos_preparacion: Mapped[float] = mapped_column(Float, default=0.0)
    minutos_por_unidad: Mapped[float] = mapped_column(Float, default=0.0)
    minutos_por_linea: Mapped[float] = mapped_column(Float, default=0.0)
    fuente: Mapped[str] = mapped_column(String(20), default=Fuente.CONFIG_FABRICA)
    es_ejemplo: Mapped[bool] = mapped_column(Boolean, default=False)
    version: Mapped[int] = mapped_column(Integer, default=1)
    vigente: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    creado: Mapped[datetime] = mapped_column(DateTime, default=ahora)
    creado_por: Mapped[str | None] = mapped_column(String(80))
    notas: Mapped[str | None] = mapped_column(Text)


class ReglaDependencia(Base):
    """Regla de ruta configurada por la fábrica cuando el documento no expresa la relación
    (p.ej. "MONTAJE-EMBALAJE PUERTAS" depende de "SOLD. MARCOS" del mismo aparato)."""

    __tablename__ = "regla_dependencia"

    id: Mapped[int] = mapped_column(primary_key=True)
    grupo_hf_origen: Mapped[str] = mapped_column(String(120))
    grupo_hf_destino: Mapped[str] = mapped_column(String(120))
    mismo_aparato: Mapped[bool] = mapped_column(Boolean, default=True)
    descripcion: Mapped[str | None] = mapped_column(String(200))
    es_ejemplo: Mapped[bool] = mapped_column(Boolean, default=False)
    activa: Mapped[bool] = mapped_column(Boolean, default=True)
