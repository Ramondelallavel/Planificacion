"""Enumeraciones de dominio. Se guardan como texto para que la BD sea legible y portable."""

from __future__ import annotations

from enum import StrEnum


class Fuente(StrEnum):
    """Sistema de origen de un dato (trazabilidad, punto 33 del pliego)."""

    PDF = "PDF"
    MRP = "MRP"
    ORTEMS = "ORTEMS"
    TEAMCENTER = "TEAMCENTER"
    CONFIG_FABRICA = "CONFIG_FABRICA"
    USUARIO = "USUARIO"
    DERIVADO = "DERIVADO"  # calculado por una regla determinista documentada
    APRENDIZAJE = "APRENDIZAJE"  # estimación aprobada a partir de históricos
    IA_SUGERENCIA = "IA_SUGERENCIA"  # nunca se usa sin validación humana


class EstadoDocumento(StrEnum):
    EN_COLA = "EN_COLA"
    PROCESANDO = "PROCESANDO"
    COMPLETADO = "COMPLETADO"
    COMPLETADO_CON_ERRORES = "COMPLETADO_CON_ERRORES"
    ERROR = "ERROR"
    DUPLICADO = "DUPLICADO"
    SUSTITUIDO = "SUSTITUIDO"  # existe una versión más reciente


class EstadoTrabajo(StrEnum):
    EN_COLA = "EN_COLA"
    PROCESANDO = "PROCESANDO"
    COMPLETADO = "COMPLETADO"
    ERROR = "ERROR"
    CANCELADO = "CANCELADO"


class TipoPagina(StrEnum):
    HOJA_GRUPO_HF = "HOJA_GRUPO_HF"  # hojas de órdenes por Grupo HF (MF, CIL, COR, ...)
    HOJA_CAB_PUERTAS = "HOJA_CAB_PUERTAS"  # formato CAB puertas batientes (S40-EH-xxxxx)
    HOJA_LCH = "HOJA_LCH"  # Hoja de Fabricación de láser de chapa
    LISTA_MATERIALES = "LISTA_MATERIALES"
    PACKING_LIST = "PACKING_LIST"
    SIN_TEXTO = "SIN_TEXTO"
    DESCONOCIDA = "DESCONOCIDA"


class EstadoOF(StrEnum):
    NO_INICIADA = "NO_INICIADA"
    LISTA = "LISTA"
    PLANIFICADA = "PLANIFICADA"
    EN_CURSO = "EN_CURSO"
    PAUSADA = "PAUSADA"
    TERMINADA = "TERMINADA"
    VALIDADA = "VALIDADA"
    BLOQUEADA = "BLOQUEADA"
    INCIDENCIA = "INCIDENCIA"
    ESPERANDO_MATERIAL = "ESPERANDO_MATERIAL"
    ESPERANDO_PROGRAMACION = "ESPERANDO_PROGRAMACION"
    ESPERANDO_RECURSO = "ESPERANDO_RECURSO"


ESTADOS_OF_CERRADOS = {EstadoOF.TERMINADA, EstadoOF.VALIDADA}


class EstadoProgramacion(StrEnum):
    """Flujo especial LCH / LaserTub (punto 13)."""

    NO_REQUIERE = "NO_REQUIERE"
    PENDIENTE_PROGRAMACION = "PENDIENTE_PROGRAMACION"
    PROGRAMADA = "PROGRAMADA"
    LISTA_PARA_FABRICAR = "LISTA_PARA_FABRICAR"


class EstadoOperacion(StrEnum):
    PENDIENTE = "PENDIENTE"
    PENDIENTE_PROGRAMACION = "PENDIENTE_PROGRAMACION"
    LISTA = "LISTA"
    PLANIFICADA = "PLANIFICADA"
    EN_CURSO = "EN_CURSO"
    PAUSADA = "PAUSADA"
    TERMINADA = "TERMINADA"
    BLOQUEADA = "BLOQUEADA"


class TipoLineaOF(StrEnum):
    SALIDA = "SALIDA"  # artículo que produce la OF (con OF destino si existe)
    SALIDA_INTERNA = "SALIDA_INTERNA"  # destino = la propia OF
    ENTRADA = "ENTRADA"  # componente fabricado en otra OF (OF origen)
    ENTRADA_INTERNA = "ENTRADA_INTERNA"  # componente fabricado dentro de la misma OF
    ENTRADA_COMPRA = "ENTRADA_COMPRA"  # componente sin OF (compra / almacén)
    CONSUMO_MATERIAL = "CONSUMO_MATERIAL"  # "Consumidos": barra, tubo, chapa...
    PIEZA_CHAPA = "PIEZA_CHAPA"  # pieza de Hoja de Fabricación LCH


class TipoDependencia(StrEnum):
    COMPONENTE = "COMPONENTE"  # la OF destino consume un componente de la OF origen
    DESTINO = "DESTINO"  # la OF origen envía su salida a la OF destino
    PLEGADO = "PLEGADO"  # pieza LCH que pasa por OF de plegado
    REGLA_CONFIG = "REGLA_CONFIG"  # regla de ruta configurada por la fábrica
    MANUAL = "MANUAL"


class TipoRecurso(StrEnum):
    MAQUINA = "MAQUINA"
    PUESTO = "PUESTO"
    PROGRAMACION = "PROGRAMACION"  # oficina técnica / programación CNC


class EstadoRecurso(StrEnum):
    OPERATIVO = "OPERATIVO"
    AVERIADO = "AVERIADO"
    MANTENIMIENTO = "MANTENIMIENTO"
    PARADO = "PARADO"


class Severidad(StrEnum):
    CRITICA = "CRITICA"  # impide generar un plan definitivo
    ERROR = "ERROR"
    ADVERTENCIA = "ADVERTENCIA"
    INFO = "INFO"


class EstadoIncidenciaDatos(StrEnum):
    ABIERTA = "ABIERTA"
    REVISADA = "REVISADA"
    RESUELTA = "RESUELTA"
    IGNORADA = "IGNORADA"


class TipoIncidenciaProduccion(StrEnum):
    AVERIA = "AVERIA"
    AUSENCIA = "AUSENCIA"
    FALTA_MATERIAL = "FALTA_MATERIAL"
    CALIDAD = "CALIDAD"
    CAMBIO_PRIORIDAD = "CAMBIO_PRIORIDAD"
    OF_URGENTE = "OF_URGENTE"
    RETRASO = "RETRASO"
    OPERACION_LENTA = "OPERACION_LENTA"
    OTRA = "OTRA"


class TipoPlan(StrEnum):
    OFICIAL = "OFICIAL"
    SIMULACION = "SIMULACION"


class EstadoPlan(StrEnum):
    BORRADOR = "BORRADOR"
    ACTIVO = "ACTIVO"
    ARCHIVADO = "ARCHIVADO"
    DESCARTADO = "DESCARTADO"


class NivelRiesgo(StrEnum):
    VERDE = "VERDE"
    AMARILLO = "AMARILLO"
    NARANJA = "NARANJA"
    ROJO = "ROJO"


ORDEN_RIESGO = {NivelRiesgo.VERDE: 0, NivelRiesgo.AMARILLO: 1, NivelRiesgo.NARANJA: 2, NivelRiesgo.ROJO: 3}


class Rol(StrEnum):
    ADMINISTRADOR = "ADMINISTRADOR"
    PLANIFICADOR = "PLANIFICADOR"
    JEFE_EQUIPO = "JEFE_EQUIPO"
    OPERARIO = "OPERARIO"
    SUPERVISOR = "SUPERVISOR"
    CONSULTA = "CONSULTA"
