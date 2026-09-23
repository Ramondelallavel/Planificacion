"""HIDRAL — Sistema inteligente de planificación, programación y control de fabricación.

Capas (ver docs/ARQUITECTURA.md):
  ingesta/        motor documental (PDF por bloques, clasificación, parsers, validación)
  modelos/        modelo de datos normalizado (SQLAlchemy)
  planificacion/  motor APS: prioridad, riesgo, programador con restricciones, replanificación
  integraciones/  capa desacoplada ORTEMS / MRP / Teamcenter
  api/            API REST (FastAPI)
"""

__version__ = "0.1.0"
