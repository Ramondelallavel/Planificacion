const DIAS = ['dom', 'lun', 'mar', 'mié', 'jue', 'vie', 'sáb']

export function fecha(iso: string | null | undefined): string {
  if (!iso) return '—'
  const d = new Date(iso)
  return `${DIAS[d.getDay()]} ${String(d.getDate()).padStart(2, '0')}/${String(d.getMonth() + 1).padStart(2, '0')} ${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`
}

export function hora(iso: string | null | undefined): string {
  if (!iso) return '—'
  const d = new Date(iso)
  return `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`
}

export function horas(h: number | null | undefined, decimales = 1): string {
  if (h === null || h === undefined) return 'DATO NO DISPONIBLE'
  return `${h.toLocaleString('es-ES', { maximumFractionDigits: decimales })} h`
}

export function minutos(m: number | null | undefined): string {
  if (m === null || m === undefined) return '—'
  const signo = m < 0 ? '−' : m > 0 ? '+' : ''
  const a = Math.abs(m)
  if (a < 60) return `${signo}${Math.round(a)} min`
  return `${signo}${Math.floor(a / 60)} h ${String(Math.round(a % 60)).padStart(2, '0')} min`
}

/** Duración sin signo (minutos → «2 h 10 min»). */
export function duracion(m: number | null | undefined): string {
  if (m === null || m === undefined) return 'DATO NO DISPONIBLE'
  return minutos(Math.abs(m)).replace('+', '')
}

export function pct(v: number | null | undefined): string {
  if (v === null || v === undefined) return '—'
  return `${Math.round(v * 100)}%`
}

export function semana(codigo: string | null | undefined): string {
  if (!codigo) return 'DATO NO DISPONIBLE'
  return `S${codigo.slice(4)} · ${codigo.slice(0, 4)}`
}

export function isoLocal(d: Date): string {
  const z = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${z(d.getMonth() + 1)}-${z(d.getDate())}T${z(d.getHours())}:${z(d.getMinutes())}`
}

export const NIVEL_TEXTO: Record<string, string> = {
  ROJO: 'Acción inmediata',
  NARANJA: 'Riesgo',
  AMARILLO: 'Vigilancia',
  VERDE: 'Normal',
}

export const ORDEN_NIVEL: Record<string, number> = { VERDE: 0, AMARILLO: 1, NARANJA: 2, ROJO: 3 }
