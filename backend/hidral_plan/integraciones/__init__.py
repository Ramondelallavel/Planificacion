"""Capa de integración desacoplada con ORTEMS, MRP y Teamcenter (puntos 30-33).

No se asume ninguna API concreta: cada sistema se abstrae con un adaptador que produce
registros normalizados. Se incluye un adaptador por fichero CSV (exportaciones habituales
de estos sistemas); un adaptador por API/BD se añade implementando la misma interfaz.

Cada dato importado deja constancia de su fuente (tabla origen) y, si choca con lo que dice
otra fuente, se aplica la matriz de SISTEMA MAESTRO y se registra la discrepancia.
"""

SISTEMA_MAESTRO: dict[str, dict[str, str]] = {
    "OF: existencia, artículo y cantidad": {"maestro": "MRP", "respaldo": "PDF de tanda"},
    "Estructura de producto / lista de materiales": {"maestro": "MRP", "respaldo": "PDF (lista de materiales)"},
    "Disponibilidad de material": {"maestro": "MRP", "respaldo": "Usuario (incidencia de falta de material)"},
    "Ruta de operaciones y tiempos": {"maestro": "MRP", "respaldo": "Configuración de fábrica (tiempos estándar) / aprendizaje aprobado"},
    "Prioridad y fechas de programación": {"maestro": "ORTEMS", "respaldo": "Motor de prioridad de este sistema"},
    "Semana de fabricación": {"maestro": "ORTEMS", "respaldo": "MRP; PDF de tanda (Sxx / Semana: AAAASS)"},
    "Información técnica: producto, planos, revisiones": {"maestro": "TEAMCENTER", "respaldo": "Descripción del PDF"},
    "Contenido de hoja: piezas, destinos, bultos, parámetros": {"maestro": "PDF de tanda", "respaldo": "MRP"},
    "Recursos, turnos, cualificaciones": {"maestro": "Este sistema (configuración de fábrica)", "respaldo": "—"},
    "Estado real de ejecución (fichajes)": {"maestro": "Este sistema", "respaldo": "—"},
}
