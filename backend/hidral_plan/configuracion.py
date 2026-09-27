"""Parámetros de negocio configurables y versionados (tabla parametro_config).

Ningún peso ni umbral está codificado de forma rígida en los algoritmos: todos se leen
de aquí. Los valores por defecto son un punto de partida razonable y quedan registrados
como tales; cualquier cambio se audita con usuario, fecha y versión.
"""

from __future__ import annotations

import copy
import re
from typing import Any

from sqlalchemy.orm import Session

from .modelos import Auditoria, ParametroConfig
from .modelos.comun import ahora

DEFECTOS: dict[str, dict[str, Any]] = {
    # Índice dinámico de prioridad (punto 14). Cada factor se normaliza a 0..1 y se pondera.
    "pesos_prioridad": {
        "descripcion": "Pesos del índice dinámico de prioridad (0..1 por factor)",
        "valor": {
            "holgura": 0.30,  # poca holgura frente a la semana objetivo → más prioridad
            "semana": 0.15,  # cercanía de la semana de fabricación
            "retraso": 0.15,  # ya fuera de plazo
            "sucesores": 0.10,  # nº de OF que esperan por esta (bloqueo aguas abajo)
            "cierre_aparato": 0.08,  # aparato casi terminado: cerrar antes de abrir otros
            "cuello_botella": 0.07,  # alimenta un recurso cuello de botella
            "prioridad_ortems": 0.10,  # prioridad importada de ORTEMS si existe
            "urgente": 0.05,  # marcada como urgente por un responsable
        },
    },
    # Objetivos del optimizador (punto 46): el principal es cumplir la semana con el menor riesgo.
    "objetivos_plan": {
        "descripcion": "Pesos de desempate del programador (el cumplimiento de semana va siempre primero)",
        "valor": {
            "agrupar_setup": 0.6,  # preferir mismo material/programa en la misma máquina
            "equilibrar_carga": 0.3,  # preferir el recurso/operario menos cargado
            "minimizar_wip": 0.1,  # preferir terminar lo empezado
            "minutos_bonificacion_setup": 20,  # adelanto máximo que se concede para agrupar sin retrasar la semana
        },
    },
    "umbrales_riesgo": {
        "descripcion": "Umbrales de holgura (horas laborables) para el nivel de riesgo",
        "valor": {
            "naranja_holgura_h": 8,
            "amarillo_holgura_h": 24,
            "utilizacion_cuello_botella": 0.85,
        },
    },
    "semana_fabricacion": {
        "descripcion": "Instante límite dentro de la semana de fabricación (0=lunes). Cumplir = terminado antes de este instante.",
        "valor": {"dia_limite": 4, "hora_limite": "23:59"},
    },
    "planificacion": {
        "descripcion": "Parámetros del programador",
        "valor": {
            "horizonte_dias": 21,
            "congelar_minutos": 60,  # lo que empieza en la próxima hora no se mueve al replanificar
            "planificar_pendiente_programacion": True,  # planificar provisionalmente tras la programación
            "unidades_trabajo": ["SALIDA", "SALIDA_INTERNA", "PIEZA_CHAPA"],
            # en secciones con programación (LCH, COR/LaserTub) solo estas operaciones necesitan programa de máquina
            "tipos_con_programa": ["CORTE_LASER", "CORTE_TALADRO", "PUNZONADO", "CORTE"],
        },
    },
    # Rendimiento de cada equipo (sección) frente a los tiempos estándar: 100 = tiempos tal cual;
    # 125 = el equipo hace el trabajo en 100/125 del tiempo; 80 = necesita un 25 % más.
    "rendimiento_secciones": {
        "descripcion": "Rendimiento de cada sección en % sobre los tiempos estándar (100 = sin ajuste)",
        "valor": {},
    },
    # Cuántos planes antiguos se guardan (cada replanificación crea uno): los definitivos y el
    # activo se guardan siempre; las simulaciones más antiguas que las últimas N se borran.
    "retencion_planes": {
        "descripcion": "Planes que se conservan: oficiales archivados y simulaciones (los definitivos siempre)",
        "valor": {"oficiales": 15, "simulaciones": 30},
    },
    "aprendizaje": {
        "descripcion": "Aprendizaje de tiempos: nunca se aplica sin aprobación",
        "valor": {"muestras_minimas": 5, "desviacion_minima": 0.10},
    },
    # Mapeo determinista de texto (Grupo HF / título de programa) a tipo de operación.
    # Se evalúa en orden; la primera coincidencia gana. Sin coincidencia → tipo GENERICA + aviso.
    "mapeo_operaciones": {
        "descripcion": "Palabra clave (en Grupo HF o título de programa) → tipo de operación",
        "valor": {
            "reglas": [
                ["PINTURA", "PINTURA"],
                ["EMBALAJE", "EMBALAJE"],
                ["PRUEBA", "PRUEBA"],
                ["LAVADO", "LAVADO"],
                ["RECTIFICADO", "RECTIFICADO"],
                ["MECANIZADO", "MECANIZADO"],
                ["PUNZONADO", "PUNZONADO"],
                ["CORTE-TALADRO", "CORTE_TALADRO"],
                ["TALADR", "CORTE_TALADRO"],
                ["SOLD", "SOLDADURA"],
                ["MONTAJE", "MONTAJE"],
                ["CORTE", "CORTE"],
                ["PLEG", "PLEGADO"],
                ["CUADRO", "MONTAJE_ELECTRICO"],
                ["BOTONERA", "MONTAJE_ELECTRICO"],
                ["PLACAS", "MONTAJE_ELECTRICO"],
                ["CAJA CONEXIONES", "MONTAJE_ELECTRICO"],
                ["DETECTORES", "MONTAJE_ELECTRICO"],
                ["CABLE", "CABLEADO"],
                ["MANGUERA", "CABLEADO"],
                ["HERRAJES", "PREPARACION"],
                ["CAJON", "PREPARACION"],
                ["BIDONES", "PREPARACION"],
                ["ELEMENTOS", "PREPARACION"],
                ["CANALETAS", "PREPARACION"],
                ["PISOS", "CORTE"],
                ["BARANDILLAS", "CORTE"],
                ["GUIAS", "CORTE"],
                ["IPN", "CORTE"],
                ["IPE", "CORTE"],
                ["GEKA", "PUNZONADO"],
                ["PUERTAS", "CORTE"],
                ["VARIOS", "CORTE"],
            ],
            # tipo por defecto de la operación principal según el flujo de la sección
            "por_flujo": {"LCH": "CORTE_LASER"},
        },
    },
}


def obtener(s: Session, clave: str) -> dict[str, Any]:
    fila = s.get(ParametroConfig, clave)
    if fila is None:
        return copy.deepcopy(DEFECTOS[clave]["valor"])
    base = copy.deepcopy(DEFECTOS.get(clave, {}).get("valor", {}))
    base.update(fila.valor or {})
    return base


_RANGOS: dict[tuple[str, str], tuple[float, float]] = {
    ("planificacion", "horizonte_dias"): (1, 120),
    ("planificacion", "congelar_minutos"): (0, 24 * 60),
    ("semana_fabricacion", "dia_limite"): (0, 6),
    ("aprendizaje", "desviacion_minima"): (0, 1),
    ("aprendizaje", "muestras_minimas"): (1, 1000),
    ("retencion_planes", "oficiales"): (1, 1000),
    ("retencion_planes", "simulaciones"): (0, 1000),
}


def _es_numero(v: Any) -> bool:
    return isinstance(v, int | float) and not isinstance(v, bool)


def validar(clave: str, valor: Any) -> None:
    """Un parámetro mal formado rompería el motor al planificar: se rechaza al guardarlo."""
    if not isinstance(valor, dict):
        raise ValueError("El valor tiene que ser un objeto {clave: valor}")
    defecto = DEFECTOS[clave]["valor"]
    for k, v in valor.items():
        if clave == "rendimiento_secciones":
            if not _es_numero(v) or not 20 <= v <= 300:
                raise ValueError(f"Rendimiento de {k}: tiene que ser un número entre 20 y 300")
            continue
        if k not in defecto:
            raise ValueError(f"{clave}: clave desconocida «{k}» (válidas: {', '.join(defecto)})")
        d = defecto[k]
        if isinstance(d, bool):
            if not isinstance(v, bool):
                raise ValueError(f"{clave}.{k}: tiene que ser sí/no")
        elif _es_numero(d):
            if not _es_numero(v) or v < 0:
                raise ValueError(f"{clave}.{k}: tiene que ser un número mayor o igual que cero")
            lo, hi = _RANGOS.get((clave, k), (0, 1e6))
            if not lo <= v <= hi:
                raise ValueError(f"{clave}.{k}: tiene que estar entre {lo:g} y {hi:g}")
            if isinstance(d, int) and not float(v).is_integer():
                raise ValueError(f"{clave}.{k}: tiene que ser un número entero")
        elif isinstance(d, str):
            if not isinstance(v, str):
                raise ValueError(f"{clave}.{k}: tiene que ser texto")
            if k.startswith("hora") and not re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d", v):
                raise ValueError(f"{clave}.{k}: hora en formato HH:MM")
        elif isinstance(d, list):
            if not isinstance(v, list):
                raise ValueError(f"{clave}.{k}: tiene que ser una lista")
            if clave == "mapeo_operaciones" and not all(isinstance(r, list) and len(r) == 2 and all(isinstance(x, str) and x for x in r) for r in v):
                raise ValueError("mapeo_operaciones.reglas: cada regla es [palabra clave, tipo de operación]")
        elif isinstance(d, dict) and not isinstance(v, dict):
            raise ValueError(f"{clave}.{k}: tiene que ser un objeto")


def guardar(s: Session, clave: str, valor: dict[str, Any], usuario: str, motivo: str | None = None) -> ParametroConfig:
    if clave not in DEFECTOS:
        raise KeyError(f"Parámetro desconocido: {clave}")
    validar(clave, valor)
    fila = s.get(ParametroConfig, clave)
    antes = obtener(s, clave)
    if fila is None:
        fila = ParametroConfig(clave=clave, valor=valor, version=1, actualizado_por=usuario, descripcion=DEFECTOS[clave]["descripcion"])
        s.add(fila)
    else:
        fila.valor = valor
        fila.version += 1
        fila.actualizado = ahora()
        fila.actualizado_por = usuario
    s.add(
        Auditoria(
            usuario=usuario,
            accion="CAMBIO_CONFIGURACION",
            entidad_tipo="PARAMETRO",
            entidad_id=clave,
            antes=antes,
            despues=valor,
            motivo=motivo,
        )
    )
    return fila


def todos(s: Session) -> dict[str, dict[str, Any]]:
    salida = {}
    for clave, meta in DEFECTOS.items():
        fila = s.get(ParametroConfig, clave)
        salida[clave] = {
            "descripcion": meta["descripcion"],
            "valor": obtener(s, clave),
            "version": fila.version if fila else 0,
            "es_defecto": fila is None,
        }
    return salida
