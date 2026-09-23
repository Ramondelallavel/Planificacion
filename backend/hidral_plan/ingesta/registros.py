"""Registros intermedios que producen los parsers (independientes de la BD).

Cada registro lleva la página y el texto de origen: la trazabilidad documental se
construye desde aquí (punto 34 del pliego).
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(slots=True)
class RegTanda:
    numero: str
    producto: str | None
    pagina: int
    texto_origen: str


@dataclass(slots=True)
class RegAparato:
    numero_control: str
    pagina: int
    texto_origen: str
    referencia: str | None = None  # "EH-36747"
    tipo: str | None = None  # "EH"
    semana_codigo: str | None = None
    semana_derivada: bool = False
    producto: str | None = None
    cliente: str | None = None
    su_referencia: str | None = None
    ffp: str | None = None
    embalaje: str | None = None
    fuente_detalle: str = "HOJA"


@dataclass(slots=True)
class RegOF:
    numero: str
    pagina: int
    texto_origen: str
    formato: str  # HOJA_GRUPO_HF | HOJA_LCH | HOJA_CAB_PUERTAS
    seccion_codigo: str | None = None
    seccion_completa: str | None = None
    grupo_hf: str | None = None
    grupo_conj: str | None = None
    descripcion: str | None = None
    modo: str | None = None
    programa_codigo: str | None = None
    programa_descripcion: str | None = None
    numero_control_titulo: str | None = None  # aparato citado en el título "EH-36747 - MONTAJE GUIA"
    semana_codigo: str | None = None
    numero_desde_casilla: bool = False  # CAB montaje-embalaje: número tomado de la casilla "Orden"


@dataclass(slots=True)
class RegLinea:
    of_numero: str
    tipo: str
    pagina: int
    texto_origen: str
    articulo_codigo: str | None = None
    articulo_descripcion: str | None = None
    posicion: str | None = None
    id_pieza: str | None = None
    parametros: str | None = None
    cantidad: float | None = None
    cantidad_texto: str | None = None
    detalle_corte: str | None = None
    material: str | None = None
    espesor_mm: float | None = None
    largo_mm: float | None = None
    ancho_mm: float | None = None
    numero_control: str | None = None
    tipo_aparato: str | None = None
    semana_codigo: str | None = None
    seccion_ref: str | None = None
    orden_ref: str | None = None
    orden_plegado: str | None = None
    operaciones_marcadas: list[str] = field(default_factory=list)


@dataclass(slots=True)
class RegConsumo:
    of_numero: str
    articulo_codigo: str | None
    descripcion: str | None
    total: float | None
    total_texto: str
    pagina: int
    tipo: str  # "Consumidos" | "Consumidos (suma)"


@dataclass(slots=True)
class RegBulto:
    numero_control: str
    numero: str  # "4" / "4.1"
    pagina: int
    fuente_detalle: str  # LISTA_MATERIALES | PACKING_LIST | HOJA_CAB
    texto_origen: str
    codigo: str | None = None
    descripcion: str | None = None
    largo_mm: float | None = None
    ancho_mm: float | None = None
    alto_mm: float | None = None
    peso_kg: float | None = None
    padre: str | None = None
    of_numero: str | None = None


@dataclass(slots=True)
class RegComponenteBulto:
    numero_control: str
    bulto_numero: str
    articulo_codigo: str
    descripcion: str | None
    parametros: str | None
    cantidad: float | None
    pagina: int
    traduccion: str | None = None  # descripción en inglés (listas extracomunitarias)


@dataclass(slots=True)
class RegAviso:
    tipo: str
    severidad: str
    mensaje: str
    pagina: int | None
    texto_origen: str | None = None
    entidad_tipo: str | None = None
    entidad_ref: str | None = None
    alternativas: list | None = None


Registro = RegTanda | RegAparato | RegOF | RegLinea | RegConsumo | RegBulto | RegComponenteBulto | RegAviso
