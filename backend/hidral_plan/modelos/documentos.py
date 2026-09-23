"""Motor documental: documentos cargados, páginas y trabajos de procesamiento."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, BigInteger, DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..db import Base
from .comun import ahora
from .enums import EstadoDocumento, EstadoTrabajo


class Documento(Base):
    """Un fichero PDF cargado. El hash identifica el contenido exacto; la clave lógica
    (p.ej. "TANDA 2210") permite reconocer nuevas versiones del mismo documento."""

    __tablename__ = "documento"

    id: Mapped[int] = mapped_column(primary_key=True)
    nombre: Mapped[str] = mapped_column(String(255))
    hash_sha256: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    tamano_bytes: Mapped[int] = mapped_column(BigInteger)
    num_paginas: Mapped[int | None] = mapped_column(Integer)
    fecha_carga: Mapped[datetime] = mapped_column(DateTime, default=ahora)
    usuario_carga: Mapped[str] = mapped_column(String(80))
    estado: Mapped[str] = mapped_column(String(32), default=EstadoDocumento.EN_COLA, index=True)
    clave_logica: Mapped[str | None] = mapped_column(String(120), index=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    documento_anterior_id: Mapped[int | None] = mapped_column(ForeignKey("documento.id"))
    ruta_almacen: Mapped[str] = mapped_column(String(500))
    resumen: Mapped[dict | None] = mapped_column(JSON)
    fecha_fin: Mapped[datetime | None] = mapped_column(DateTime)

    paginas: Mapped[list[PaginaDocumento]] = relationship(back_populates="documento", cascade="all, delete-orphan")


class PaginaDocumento(Base):
    """Metadatos y texto original de cada página (almacenamiento documental para auditoría).
    El texto se guarda al procesar la página y no se vuelve a cargar en memoria salvo consulta."""

    __tablename__ = "pagina_documento"
    __table_args__ = (Index("ix_pagina_doc_num", "documento_id", "numero", unique=True),)

    id: Mapped[int] = mapped_column(primary_key=True)
    documento_id: Mapped[int] = mapped_column(ForeignKey("documento.id", ondelete="CASCADE"))
    numero: Mapped[int] = mapped_column(Integer)
    bloque: Mapped[int] = mapped_column(Integer)
    tipo: Mapped[str] = mapped_column(String(32), index=True)
    metodo_extraccion: Mapped[str] = mapped_column(String(16))  # TEXTO | OCR | NINGUNO
    num_caracteres: Mapped[int] = mapped_column(Integer, default=0)
    seccion_codigo: Mapped[str | None] = mapped_column(String(32))
    grupo_hf: Mapped[str | None] = mapped_column(String(120))
    pagina_de: Mapped[str | None] = mapped_column(String(16))  # "1 de 3" tal y como aparece
    ofs_detectadas: Mapped[list | None] = mapped_column(JSON)
    avisos: Mapped[int] = mapped_column(Integer, default=0)
    texto: Mapped[str | None] = mapped_column(Text)

    documento: Mapped[Documento] = relationship(back_populates="paginas")


class TrabajoProcesamiento(Base):
    """Cola de trabajos persistente. Un trabajador la consume en segundo plano
    (FOR UPDATE SKIP LOCKED en PostgreSQL)."""

    __tablename__ = "trabajo_procesamiento"

    id: Mapped[int] = mapped_column(primary_key=True)
    documento_id: Mapped[int] = mapped_column(ForeignKey("documento.id", ondelete="CASCADE"), index=True)
    tipo: Mapped[str] = mapped_column(String(32), default="INGESTA_PDF")
    estado: Mapped[str] = mapped_column(String(16), default=EstadoTrabajo.EN_COLA, index=True)
    paginas_totales: Mapped[int] = mapped_column(Integer, default=0)
    paginas_procesadas: Mapped[int] = mapped_column(Integer, default=0)
    bloque_actual: Mapped[int] = mapped_column(Integer, default=0)
    bloques_totales: Mapped[int] = mapped_column(Integer, default=0)
    tamano_bloque: Mapped[int] = mapped_column(Integer, default=0)
    contadores: Mapped[dict | None] = mapped_column(JSON)
    fase: Mapped[str | None] = mapped_column(String(64))
    creado: Mapped[datetime] = mapped_column(DateTime, default=ahora)
    inicio: Mapped[datetime | None] = mapped_column(DateTime)
    fin: Mapped[datetime | None] = mapped_column(DateTime)
    latido: Mapped[datetime | None] = mapped_column(DateTime)
    eta_segundos: Mapped[int | None] = mapped_column(Integer)
    intentos: Mapped[int] = mapped_column(Integer, default=0)
    trabajador: Mapped[str | None] = mapped_column(String(64))
    mensaje_error: Mapped[str | None] = mapped_column(Text)
