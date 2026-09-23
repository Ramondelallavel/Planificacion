"""Calendario laboral: ventanas de turno, intervalos libres y reparto de trabajo en tramos.

Una operación puede partirse en fin de turno o en una pausa (se retoma en el siguiente
turno), pero nunca se intercala otro trabajo en medio: si el hueco no permite hacerla
entera con los tramos laborables consecutivos, se busca un inicio posterior.
"""

from __future__ import annotations

from bisect import bisect_left, bisect_right
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta

Intervalo = tuple[datetime, datetime]


@dataclass(frozen=True)
class TurnoDef:
    codigo: str
    inicio: time
    fin: time
    dias: frozenset[int]
    pausas: tuple[tuple[time, time], ...] = ()


def _hora(txt: str) -> time:
    h, m = txt.split(":")
    return time(int(h), int(m))


def turno_desde_modelo(t) -> TurnoDef:
    pausas = tuple((_hora(p["inicio"]), _hora(p["fin"])) for p in (t.pausas or []))
    return TurnoDef(t.codigo, _hora(t.hora_inicio), _hora(t.hora_fin), frozenset(t.dias_semana or []), pausas)


def ventanas_turno(turno: TurnoDef, desde: datetime, hasta: datetime, festivos: set[date] | None = None) -> list[Intervalo]:
    festivos = festivos or set()
    salida: list[Intervalo] = []
    dia = desde.date() - timedelta(days=1)
    while datetime.combine(dia, time.min) <= hasta:
        if dia.weekday() in turno.dias and dia not in festivos:
            ini = datetime.combine(dia, turno.inicio)
            fin = datetime.combine(dia, turno.fin)
            if fin <= ini:
                fin += timedelta(days=1)
            cortes = [ini]
            for p0, p1 in sorted(turno.pausas):
                a = datetime.combine(dia, p0)
                b = datetime.combine(dia, p1)
                if a < ini:
                    a += timedelta(days=1)
                    b += timedelta(days=1)
                if ini < a < fin and a < b:
                    cortes += [a, min(b, fin)]
            cortes.append(fin)
            for a, b in zip(cortes[::2], cortes[1::2], strict=False):
                a2, b2 = max(a, desde), min(b, hasta)
                if a2 < b2:
                    salida.append((a2, b2))
        dia += timedelta(days=1)
    return fusionar(salida)


def fusionar(intervalos: list[Intervalo]) -> list[Intervalo]:
    if not intervalos:
        return []
    ordenados = sorted(intervalos)
    salida = [ordenados[0]]
    for a, b in ordenados[1:]:
        if a <= salida[-1][1]:
            if b > salida[-1][1]:
                salida[-1] = (salida[-1][0], b)
        else:
            salida.append((a, b))
    return salida


def restar(base: list[Intervalo], quitar: list[Intervalo]) -> list[Intervalo]:
    if not quitar:
        return list(base)
    quitar = fusionar(quitar)
    salida: list[Intervalo] = []
    for a, b in base:
        cur = a
        for q0, q1 in quitar:
            if q1 <= cur or q0 >= b:
                continue
            if q0 > cur:
                salida.append((cur, q0))
            cur = max(cur, q1)
            if cur >= b:
                break
        if cur < b:
            salida.append((cur, b))
    return salida


def interseccion(a: list[Intervalo], b: list[Intervalo]) -> list[Intervalo]:
    i = j = 0
    salida: list[Intervalo] = []
    while i < len(a) and j < len(b):
        ini = max(a[i][0], b[j][0])
        fin = min(a[i][1], b[j][1])
        if ini < fin:
            salida.append((ini, fin))
        if a[i][1] < b[j][1]:
            i += 1
        else:
            j += 1
    return salida


def minutos_en(intervalos: list[Intervalo], desde: datetime, hasta: datetime) -> float:
    total = 0.0
    for a, b in intervalos:
        if b <= desde or a >= hasta:
            continue
        total += (min(b, hasta) - max(a, desde)).total_seconds() / 60
    return total


class Ocupacion:
    """Tramos ocupados de un recurso o de un operario, ordenados para búsqueda rápida."""

    __slots__ = ("ids", "inicios", "tramos")

    def __init__(self) -> None:
        self.tramos: list[Intervalo] = []
        self.inicios: list[datetime] = []
        self.ids: list[int | None] = []

    def agregar(self, tramos: list[Intervalo], ident: int | None = None) -> None:
        for t in tramos:
            i = bisect_left(self.inicios, t[0])
            self.inicios.insert(i, t[0])
            self.tramos.insert(i, t)
            self.ids.insert(i, ident)

    def quitar(self, ident: int) -> None:
        conservar = [k for k, x in enumerate(self.ids) if x != ident]
        self.tramos = [self.tramos[k] for k in conservar]
        self.inicios = [self.inicios[k] for k in conservar]
        self.ids = [self.ids[k] for k in conservar]

    def id_en(self, tramo: Intervalo) -> int | None:
        i = bisect_left(self.inicios, tramo[0])
        while i < len(self.tramos) and self.inicios[i] == tramo[0]:
            if self.tramos[i] == tramo:
                return self.ids[i]
            i += 1
        return None

    def anterior_id(self, instante: datetime) -> int | None:
        i = bisect_right(self.inicios, instante) - 1
        while i >= 0 and self.tramos[i][1] > instante:
            i -= 1
        return self.ids[i] if i >= 0 else None

    def primer_conflicto(self, tramos: list[Intervalo]) -> Intervalo | None:
        """Los tramos guardados no se solapan entre sí: basta mirar el que empieza justo antes
        de cada tramo consultado y el siguiente."""
        for a, b in tramos:
            i = bisect_right(self.inicios, a) - 1
            if i >= 0 and self.tramos[i][1] > a:
                return self.tramos[i]
            j = i + 1
            if j < len(self.tramos) and self.inicios[j] < b:
                return self.tramos[j]
        return None

    def minutos(self, desde: datetime, hasta: datetime) -> float:
        return minutos_en(self.tramos, desde, hasta)

    def anterior(self, instante: datetime) -> Intervalo | None:
        i = bisect_right(self.inicios, instante) - 1
        return self.tramos[i] if i >= 0 else None


class Ventanas:
    """Ventanas laborables ordenadas con índice de finales para búsquedas binarias."""

    __slots__ = ("fines", "lista")

    def __init__(self, lista: list[Intervalo]) -> None:
        self.lista = lista
        self.fines = [v[1] for v in lista]

    def minutos(self, desde: datetime, hasta: datetime) -> float:
        return minutos_en(self.lista, desde, hasta)

    def siguiente_inicio(self, instante: datetime) -> datetime | None:
        i = bisect_right(self.fines, instante)
        if i >= len(self.lista):
            return None
        return max(self.lista[i][0], instante)


def repartir(ventanas: Ventanas, inicio: datetime, minutos: float) -> list[Intervalo] | None:
    """Tramos consecutivos de trabajo que suman `minutos` empezando en `inicio` (o en la
    siguiente ventana laborable). None si las ventanas no alcanzan."""
    restante = timedelta(minutes=minutos)
    tramos: list[Intervalo] = []
    i = bisect_right(ventanas.fines, inicio)
    lista = ventanas.lista
    while i < len(lista) and restante > timedelta(0):
        a, b = lista[i]
        if not tramos:
            a = max(a, inicio)
        if a < b:
            uso = min(b - a, restante)
            tramos.append((a, a + uso))
            restante -= uso
        i += 1
    if restante > timedelta(seconds=1):
        return None
    if not tramos:
        ini = ventanas.siguiente_inicio(inicio) or inicio
        return [(ini, ini)]
    return tramos
