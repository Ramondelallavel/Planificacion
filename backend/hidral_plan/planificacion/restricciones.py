"""Validación de restricciones duras de una asignación (cambios manuales, arrastres en el Gantt).

Una decisión físicamente imposible nunca se acepta: se devuelve la lista de violaciones y el
cambio se rechaza. Las advertencias (p.ej. sucesoras que habrá que mover) no bloquean.
"""

from __future__ import annotations

from datetime import timedelta

from .calendario import minutos_en
from .modelo import AsigP, Instantanea
from .programador import _ventanas_combinadas


def _solapa(a: list, b: list) -> bool:
    return any(x0 < y1 and y0 < x1 for x0, x1 in a for y0, y1 in b)


def validar_asignacion(inst: Instantanea, a: AsigP, plan: dict[int, AsigP]) -> tuple[list[str], list[str]]:
    errores: list[str] = []
    avisos: list[str] = []
    op = inst.ops.get(a.op_id)
    if op is None:
        return ["La operación no está pendiente (terminada o fuera del plan)."], []
    r = inst.recursos.get(a.recurso_id) if a.recurso_id is not None else None
    if r is None:
        errores.append("Recurso inexistente o inactivo.")
    elif not r.puede(op):
        errores.append(
            f"El recurso {r.codigo} no puede hacer la operación {op.tipo} de la sección {op.seccion}"
            + (f" (el programa indica {op.recurso_preferido})" if op.recurso_preferido else "")
            + "."
        )
    o = inst.operarios.get(a.operario_id) if a.operario_id is not None else None
    if r is not None and r.requiere_operario:
        if o is None:
            errores.append(f"{r.codigo} necesita un operario asignado.")
        elif not o.cualificado(r, op):
            errores.append(f"{o.nombre} ({o.codigo}) no está cualificado para {r.codigo} / {op.tipo}.")
    if a.inicio < inst.ahora - timedelta(minutes=1):
        errores.append("No se puede programar en el pasado.")
    if op.material_bloqueado:
        errores.append("La OF no tiene material disponible (sin fecha prevista).")
    if op.liberacion and a.inicio < op.liberacion:
        errores.append(f"El material no está disponible hasta {op.liberacion:%d/%m %H:%M}.")
    if r is not None and (o is not None or not r.requiere_operario):
        vent = _ventanas_combinadas(inst, r, o if r.requiere_operario else None)
        for x, y in a.tramos:
            if minutos_en(vent.lista, x, y) + 0.5 < (y - x).total_seconds() / 60:
                errores.append(f"El tramo {x:%d/%m %H:%M}-{y:%H:%M} cae fuera de turno, en una pausa, en una parada del recurso o en una ausencia del operario.")
                break
    trabajado = sum((y - x).total_seconds() / 60 for x, y in a.tramos)
    necesario = max(0.0, (op.duracion or 0) - op.minutos_hechos)
    if op.duracion is not None and trabajado + 0.5 < necesario:
        errores.append(f"Los tramos suman {trabajado:.0f} min y la operación necesita {necesario:.0f} min.")
    for otra in plan.values():
        if otra.op_id == a.op_id:
            continue
        if a.recurso_id is not None and otra.recurso_id == a.recurso_id and otra.unidad == a.unidad and _solapa(a.tramos, otra.tramos):
            errores.append(f"Solapa en {r.codigo if r else a.recurso_id} con la OF {inst.of_numeros.get(otra.of_id)} ({otra.inicio:%d/%m %H:%M}-{otra.fin:%H:%M}).")
        if a.operario_id is not None and otra.operario_id == a.operario_id and _solapa(a.tramos, otra.tramos):
            errores.append(f"El operario ya tiene asignada la OF {inst.of_numeros.get(otra.of_id)} en ese horario.")
    for p in op.predecesoras:
        pa = plan.get(p)
        pred = inst.ops.get(p)
        if pa is None:
            if pred is not None:
                errores.append(f"La predecesora OF {pred.of_numero} ({pred.tipo}) no está planificada: no se puede fijar esta operación.")
        elif pa.fin > a.inicio:
            errores.append(f"Empezaría antes de que termine la predecesora OF {pred.of_numero if pred else p} ({pa.fin:%d/%m %H:%M}).")
    for sid in inst.sucesoras_op(a.op_id):
        sa = plan.get(sid)
        if sa is not None and sa.inicio < a.fin:
            avisos.append(f"La sucesora OF {inst.ops[sid].of_numero} empieza antes del nuevo fin: se replanificará.")
    if op.pendiente_programa:
        avisos.append("Operación pendiente de programación: no podrá iniciarse hasta registrar el programa.")
    return errores, avisos
