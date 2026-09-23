"""Estructura de fabricación: TANDA → APARATO → BULTO → COMPONENTE → OF → OPERACIÓN → RECURSO.

Reglas del pliego respetadas por el modelo:
  * Una tanda NO tiene un número fijo de aparatos (relación 1:N sin límite).
  * Una OF puede afectar a varios aparatos (hojas "Serie" o "Conjunta" que agrupan
    piezas de varios pedidos) → tabla of_aparato.
  * Las dependencias entre OF salen de los datos (columnas Sección/Orden, Destino,
    Pleg.) y guardan sus evidencias (página y artículo).
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..db import Base
from .comun import ahora
from .enums import EstadoOF, EstadoOperacion, EstadoProgramacion, Fuente, NivelRiesgo


class Tanda(Base):
    __tablename__ = "tanda"

    id: Mapped[int] = mapped_column(primary_key=True)
    numero: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    producto: Mapped[str | None] = mapped_column(String(120))
    semana_codigo: Mapped[str | None] = mapped_column(String(8), index=True)  # AAAASS, p.ej. 202640
    fecha_creacion: Mapped[datetime] = mapped_column(DateTime, default=ahora)
    estado: Mapped[str] = mapped_column(String(24), default="ACTIVA", index=True)
    prioridad: Mapped[float | None] = mapped_column(Float, index=True)
    prioridad_manual: Mapped[float | None] = mapped_column(Float)
    carga_total_h: Mapped[float | None] = mapped_column(Float)
    carga_restante_h: Mapped[float | None] = mapped_column(Float)
    progreso: Mapped[float] = mapped_column(Float, default=0.0)
    riesgo_nivel: Mapped[str] = mapped_column(String(12), default=NivelRiesgo.VERDE, index=True)
    riesgo_puntuacion: Mapped[float | None] = mapped_column(Float)
    riesgo_motivos: Mapped[list | None] = mapped_column(JSON)
    documento_id: Mapped[int | None] = mapped_column(ForeignKey("documento.id"))
    incluida_en_plan: Mapped[bool] = mapped_column(Boolean, default=True)

    aparatos: Mapped[list[Aparato]] = relationship(back_populates="tanda", order_by="Aparato.numero_control")


class Aparato(Base):
    """Aparato / pedido. Se identifica por el número de control (p.ej. 36747)."""

    __tablename__ = "aparato"
    __table_args__ = (UniqueConstraint("tanda_id", "numero_control", name="uq_aparato_tanda_control"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    tanda_id: Mapped[int] = mapped_column(ForeignKey("tanda.id", ondelete="CASCADE"), index=True)
    referencia: Mapped[str] = mapped_column(String(32), index=True)  # "EH-36747"
    numero_control: Mapped[str] = mapped_column(String(16), index=True)  # "36747"
    tipo: Mapped[str | None] = mapped_column(String(16))  # "EH"
    producto: Mapped[str | None] = mapped_column(String(160))  # "ELEVADOR MONTACARGAS HO"
    cliente: Mapped[str | None] = mapped_column(String(160))
    su_referencia: Mapped[str | None] = mapped_column(String(64))
    ffp: Mapped[str | None] = mapped_column(String(32))
    embalaje: Mapped[str | None] = mapped_column(String(64))
    extracomunitario: Mapped[bool | None] = mapped_column(Boolean)
    semana_codigo: Mapped[str | None] = mapped_column(String(8), index=True)
    estado: Mapped[str] = mapped_column(String(24), default="EN_PROCESO", index=True)
    carga_estimada_h: Mapped[float | None] = mapped_column(Float)
    carga_restante_h: Mapped[float | None] = mapped_column(Float)
    progreso: Mapped[float] = mapped_column(Float, default=0.0)
    riesgo_nivel: Mapped[str] = mapped_column(String(12), default=NivelRiesgo.VERDE, index=True)
    riesgo_motivos: Mapped[list | None] = mapped_column(JSON)
    fin_previsto: Mapped[datetime | None] = mapped_column(DateTime)

    tanda: Mapped[Tanda] = relationship(back_populates="aparatos")
    bultos: Mapped[list[Bulto]] = relationship(back_populates="aparato", cascade="all, delete-orphan", order_by="Bulto.orden")


class Bulto(Base):
    """Bulto físico del aparato (lista de materiales / packing list). Puede tener sub-bultos (4.1, 4.2...)."""

    __tablename__ = "bulto"
    __table_args__ = (UniqueConstraint("aparato_id", "numero", name="uq_bulto_aparato_numero"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    aparato_id: Mapped[int] = mapped_column(ForeignKey("aparato.id", ondelete="CASCADE"), index=True)
    padre_id: Mapped[int | None] = mapped_column(ForeignKey("bulto.id"))
    numero: Mapped[str] = mapped_column(String(16))  # "4" o "4.1" tal y como aparece
    orden: Mapped[int] = mapped_column(Integer, default=0)
    codigo: Mapped[str | None] = mapped_column(String(32))  # "B3021000/4"
    descripcion: Mapped[str | None] = mapped_column(String(200))
    largo_mm: Mapped[float | None] = mapped_column(Float)
    ancho_mm: Mapped[float | None] = mapped_column(Float)
    alto_mm: Mapped[float | None] = mapped_column(Float)
    peso_kg: Mapped[float | None] = mapped_column(Float)
    estado: Mapped[str] = mapped_column(String(24), default="PENDIENTE")
    of_id: Mapped[int | None] = mapped_column(ForeignKey("orden_fabricacion.id"))  # OF de embalaje asociada si se conoce
    fuentes: Mapped[list | None] = mapped_column(JSON)  # ["LISTA_MATERIALES p.87", "PACKING_LIST p.98"]

    aparato: Mapped[Aparato] = relationship(back_populates="bultos")
    componentes: Mapped[list[ComponenteBulto]] = relationship(back_populates="bulto", cascade="all, delete-orphan")


class ComponenteBulto(Base):
    __tablename__ = "componente_bulto"

    id: Mapped[int] = mapped_column(primary_key=True)
    bulto_id: Mapped[int] = mapped_column(ForeignKey("bulto.id", ondelete="CASCADE"), index=True)
    articulo_codigo: Mapped[str] = mapped_column(String(40), index=True)
    descripcion: Mapped[str | None] = mapped_column(String(240))
    parametros: Mapped[str | None] = mapped_column(String(240))
    traduccion: Mapped[str | None] = mapped_column(String(240))
    cantidad: Mapped[float | None] = mapped_column(Float)
    pagina: Mapped[int | None] = mapped_column(Integer)
    of_numero: Mapped[str | None] = mapped_column(String(16))  # OF que fabrica/embala el componente, si se conoce

    bulto: Mapped[Bulto] = relationship(back_populates="componentes")


class OFAparato(Base):
    """Relación N:M entre OF y aparato (una OF de corte puede servir a varios aparatos)."""

    __tablename__ = "of_aparato"

    of_id: Mapped[int] = mapped_column(ForeignKey("orden_fabricacion.id", ondelete="CASCADE"), primary_key=True)
    aparato_id: Mapped[int] = mapped_column(ForeignKey("aparato.id", ondelete="CASCADE"), primary_key=True, index=True)
    lineas: Mapped[int] = mapped_column(Integer, default=0)


class OrdenFabricacion(Base):
    __tablename__ = "orden_fabricacion"
    __table_args__ = (
        Index("ix_of_tanda_estado", "tanda_id", "estado"),
        Index("ix_of_seccion_estado", "seccion_codigo", "estado"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    numero: Mapped[str] = mapped_column(String(16), unique=True, index=True)  # "917251"
    tanda_id: Mapped[int | None] = mapped_column(ForeignKey("tanda.id"), index=True)
    aparato_id: Mapped[int | None] = mapped_column(ForeignKey("aparato.id"), index=True)  # aparato principal si es único
    seccion_codigo: Mapped[str | None] = mapped_column(String(32), index=True)  # "MF", "LCH", "COR"...
    seccion_completa: Mapped[str | None] = mapped_column(String(40))  # "SC000003-MF"
    grupo_hf: Mapped[str | None] = mapped_column(String(120), index=True)
    grupo_conj: Mapped[str | None] = mapped_column(String(120))  # LCH: "SG6 NCX PUERTAS EH"
    descripcion: Mapped[str | None] = mapped_column(String(240))  # "EH-36747 - MONTAJE GUIA"
    modo: Mapped[str | None] = mapped_column(String(24))  # Conjunta-Pedido | Serie | Conjunta
    programa_codigo: Mapped[str | None] = mapped_column(String(32))  # "PL025286/A"
    programa_descripcion: Mapped[str | None] = mapped_column(String(160))  # "CORTE-TALADRO LASERTUB"
    cantidad_total: Mapped[float | None] = mapped_column(Float)
    semana_codigo: Mapped[str | None] = mapped_column(String(8), index=True)
    estado: Mapped[str] = mapped_column(String(28), default=EstadoOF.NO_INICIADA, index=True)
    estado_programacion: Mapped[str] = mapped_column(String(28), default=EstadoProgramacion.NO_REQUIERE)
    prioridad: Mapped[float | None] = mapped_column(Float, index=True)
    prioridad_ortems: Mapped[float | None] = mapped_column(Float)
    urgente: Mapped[bool] = mapped_column(Boolean, default=False)
    bloqueada_manual: Mapped[bool] = mapped_column(Boolean, default=False)
    material_disponible: Mapped[bool | None] = mapped_column(Boolean)  # None = DATO NO DISPONIBLE
    material_disponible_desde: Mapped[datetime | None] = mapped_column(DateTime)
    # Para OF que este sistema no planifica (referenciadas sin hoja, otras plantas, externas):
    # fecha prevista en que su salida estará disponible, informada por ORTEMS/MRP o un usuario.
    disponible_prevista: Mapped[datetime | None] = mapped_column(DateTime)
    fuente_disponible: Mapped[str | None] = mapped_column(String(20))
    horas_estimadas: Mapped[float | None] = mapped_column(Float)
    horas_reales: Mapped[float | None] = mapped_column(Float)
    fecha_prevista_inicio: Mapped[datetime | None] = mapped_column(DateTime, index=True)
    fecha_prevista_fin: Mapped[datetime | None] = mapped_column(DateTime, index=True)
    fecha_real_inicio: Mapped[datetime | None] = mapped_column(DateTime)
    fecha_real_fin: Mapped[datetime | None] = mapped_column(DateTime)
    recurso_requerido: Mapped[str | None] = mapped_column(String(64))
    tiene_hoja: Mapped[bool] = mapped_column(Boolean, default=True)  # False = solo referenciada en otras hojas
    riesgo_nivel: Mapped[str] = mapped_column(String(12), default=NivelRiesgo.VERDE, index=True)
    fuente: Mapped[str] = mapped_column(String(20), default=Fuente.PDF)
    documento_id: Mapped[int | None] = mapped_column(ForeignKey("documento.id"), index=True)
    paginas: Mapped[list | None] = mapped_column(JSON)
    consumos: Mapped[list | None] = mapped_column(JSON)  # [{articulo, descripcion, total, pagina}]
    parametros_extra: Mapped[dict | None] = mapped_column(JSON)

    lineas: Mapped[list[LineaOF]] = relationship(back_populates="of", cascade="all, delete-orphan", order_by="LineaOF.id")
    operaciones: Mapped[list[Operacion]] = relationship(back_populates="of", cascade="all, delete-orphan", order_by="Operacion.secuencia")


class LineaOF(Base):
    """Fila de una hoja: pieza/artículo con cantidad, parámetros y referencias (sección/orden, destino)."""

    __tablename__ = "linea_of"

    id: Mapped[int] = mapped_column(primary_key=True)
    of_id: Mapped[int] = mapped_column(ForeignKey("orden_fabricacion.id", ondelete="CASCADE"), index=True)
    tipo: Mapped[str] = mapped_column(String(20), index=True)
    articulo_codigo: Mapped[str | None] = mapped_column(String(40), index=True)  # "3001000/4"
    articulo_descripcion: Mapped[str | None] = mapped_column(String(240))
    posicion: Mapped[str | None] = mapped_column(String(16))  # LCH: "1039"
    id_pieza: Mapped[str | None] = mapped_column(String(40))  # COR: "EH-36747-0305"
    parametros: Mapped[str | None] = mapped_column(Text)  # texto original "R=2670 F=230 ..."
    parametros_dict: Mapped[dict | None] = mapped_column(JSON)
    cantidad: Mapped[float | None] = mapped_column(Float)
    cantidad_texto: Mapped[str | None] = mapped_column(String(32))
    detalle_corte: Mapped[str | None] = mapped_column(String(64))  # "2x235", "1x4410", "1,298"
    material: Mapped[str | None] = mapped_column(String(32))  # LCH: "DC01"
    espesor_mm: Mapped[float | None] = mapped_column(Float)
    largo_mm: Mapped[float | None] = mapped_column(Float)
    ancho_mm: Mapped[float | None] = mapped_column(Float)
    aparato_id: Mapped[int | None] = mapped_column(ForeignKey("aparato.id"), index=True)
    numero_control: Mapped[str | None] = mapped_column(String(16))
    semana_codigo: Mapped[str | None] = mapped_column(String(8))
    seccion_ref: Mapped[str | None] = mapped_column(String(32))  # sección de origen/destino
    orden_ref: Mapped[str | None] = mapped_column(String(16), index=True)  # OF de origen/destino
    orden_plegado: Mapped[str | None] = mapped_column(String(16))  # LCH columna Pleg.
    operaciones_marcadas: Mapped[list | None] = mapped_column(JSON)  # LCH: ["Pleg."]
    pagina: Mapped[int | None] = mapped_column(Integer)
    texto_origen: Mapped[str | None] = mapped_column(Text)

    of: Mapped[OrdenFabricacion] = relationship(back_populates="lineas")


class Operacion(Base):
    __tablename__ = "operacion"
    __table_args__ = (Index("ix_operacion_estado", "estado"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    of_id: Mapped[int] = mapped_column(ForeignKey("orden_fabricacion.id", ondelete="CASCADE"), index=True)
    secuencia: Mapped[int] = mapped_column(Integer, default=10)
    tipo: Mapped[str] = mapped_column(String(32))  # CORTE, PLEGADO, SOLDADURA, MONTAJE, PINTURA, EMBALAJE...
    descripcion: Mapped[str | None] = mapped_column(String(200))
    seccion_codigo: Mapped[str | None] = mapped_column(String(32), index=True)
    recurso_preferido: Mapped[str | None] = mapped_column(String(64))  # código de recurso deducido (p.ej. LASERTUB)
    duracion_estimada_min: Mapped[float | None] = mapped_column(Float)  # None = DATO NO DISPONIBLE
    duracion_real_min: Mapped[float | None] = mapped_column(Float)
    origen_duracion: Mapped[str | None] = mapped_column(String(400))
    tiempo_estandar_id: Mapped[int | None] = mapped_column(ForeignKey("tiempo_estandar.id"))
    estado: Mapped[str] = mapped_column(String(28), default=EstadoOperacion.PENDIENTE)
    requiere_programa: Mapped[bool] = mapped_column(Boolean, default=False)
    operacion_anterior_id: Mapped[int | None] = mapped_column(ForeignKey("operacion.id"))
    cantidad: Mapped[float | None] = mapped_column(Float)
    cantidad_hecha: Mapped[float] = mapped_column(Float, default=0.0)
    fuente: Mapped[str] = mapped_column(String(20), default=Fuente.DERIVADO)
    familia_setup: Mapped[str | None] = mapped_column(String(80))  # agrupación para reducir cambios

    of: Mapped[OrdenFabricacion] = relationship(back_populates="operaciones")


class DependenciaOF(Base):
    """OF destino depende de OF origen (origen debe terminar antes)."""

    __tablename__ = "dependencia_of"
    __table_args__ = (UniqueConstraint("of_origen_id", "of_destino_id", name="uq_dependencia"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    of_origen_id: Mapped[int] = mapped_column(ForeignKey("orden_fabricacion.id", ondelete="CASCADE"), index=True)
    of_destino_id: Mapped[int] = mapped_column(ForeignKey("orden_fabricacion.id", ondelete="CASCADE"), index=True)
    tipo: Mapped[str] = mapped_column(String(20))
    evidencias: Mapped[list | None] = mapped_column(JSON)  # [{"pagina": 1, "articulo": "3005100/2", "tipo": "COMPONENTE"}]
    fuente: Mapped[str] = mapped_column(String(20), default=Fuente.PDF)
    activa: Mapped[bool] = mapped_column(Boolean, default=True)


class Articulo(Base):
    """Maestro ligero de artículos (código base + revisión). Teamcenter es el maestro técnico."""

    __tablename__ = "articulo"

    codigo: Mapped[str] = mapped_column(String(40), primary_key=True)  # "3001000/4"
    codigo_base: Mapped[str] = mapped_column(String(32), index=True)  # "3001000"
    revision: Mapped[str | None] = mapped_column(String(8))
    descripcion: Mapped[str | None] = mapped_column(String(240))
    fuente: Mapped[str] = mapped_column(String(20), default=Fuente.PDF)
    datos_tecnicos: Mapped[dict | None] = mapped_column(JSON)  # Teamcenter: planos, revisiones...
    actualizado: Mapped[datetime] = mapped_column(DateTime, default=ahora)


class ProgramaCNC(Base):
    """Programa de máquina (nesting LCH, programa LaserTub...). Su existencia desbloquea la fabricación."""

    __tablename__ = "programa_cnc"

    id: Mapped[int] = mapped_column(primary_key=True)
    codigo: Mapped[str] = mapped_column(String(40), index=True)
    of_id: Mapped[int] = mapped_column(ForeignKey("orden_fabricacion.id", ondelete="CASCADE"), index=True)
    recurso_codigo: Mapped[str | None] = mapped_column(String(64))
    estado: Mapped[str] = mapped_column(String(24), default="PROGRAMADA")
    fuente: Mapped[str] = mapped_column(String(20))
    registrado: Mapped[datetime] = mapped_column(DateTime, default=ahora)
    registrado_por: Mapped[str | None] = mapped_column(String(80))
    notas: Mapped[str | None] = mapped_column(Text)
