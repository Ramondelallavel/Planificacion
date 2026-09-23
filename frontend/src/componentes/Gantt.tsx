import { useMemo, useRef, useState, type MouseEvent as RMouseEvent } from 'react'
import { fecha, hora } from '../formato'
import type { Asignacion, RecursoGantt } from '../tipos'

export type Zoom = 'hora' | 'turno' | 'dia'
export type Vista = 'recurso' | 'tanda'

const PX_HORA: Record<Zoom, number> = { hora: 70, turno: 22, dia: 7 }
const ALTO_FILA = 30
const ANCHO_ETQ = 190
const SNAP_MIN = 5

interface Fila {
  clave: string
  etiqueta: string
  sub?: string
  grupo: string
  items: Asignacion[]
}

interface Props {
  asignaciones: Asignacion[]
  recursos: RecursoGantt[]
  turnos: { turno: string; inicio: string; fin: string }[]
  ahora: string
  zoom: Zoom
  vista: Vista
  seleccion: number | null
  onSeleccionar: (a: Asignacion) => void
  onMover?: (a: Asignacion, nuevoInicio: Date) => void
}

export default function Gantt({ asignaciones, recursos, turnos, ahora, zoom, vista, seleccion, onSeleccionar, onMover }: Props) {
  const px = PX_HORA[zoom] / 3600000
  const [arrastre, setArrastre] = useState<{ id: number; x0: number; dx: number } | null>(null)
  const movido = useRef(false)

  const { t0, t1 } = useMemo(() => {
    const ahoraMs = new Date(ahora).getTime()
    const ini = Math.min(ahoraMs - 2 * 3600000, ...asignaciones.map((a) => new Date(a.inicio).getTime()))
    const fin = Math.max(ahoraMs + 24 * 3600000, ...asignaciones.map((a) => new Date(a.fin).getTime()))
    const d0 = new Date(ini)
    d0.setHours(0, 0, 0, 0)
    const d1 = new Date(fin)
    d1.setHours(24, 0, 0, 0)
    return { t0: d0.getTime(), t1: d1.getTime() }
  }, [asignaciones, ahora])

  const filas: Fila[] = useMemo(() => {
    if (vista === 'recurso') {
      const porRec = new Map<string, Asignacion[]>()
      for (const a of asignaciones) {
        const k = `${a.recurso_id}:${a.unidad}`
        porRec.set(k, [...(porRec.get(k) ?? []), a])
      }
      const salida: Fila[] = []
      for (const r of recursos) {
        for (let u = 0; u < Math.max(1, r.capacidad); u++) {
          // también se muestran los recursos sin carga, para ver la capacidad libre
          const items = porRec.get(`${r.id}:${u}`) ?? []
          salida.push({ clave: `${r.id}:${u}`, etiqueta: r.capacidad > 1 ? `${r.codigo} #${u + 1}` : r.codigo, sub: r.estado !== 'OPERATIVO' ? r.estado : r.nombre, grupo: r.seccion ?? '—', items })
        }
      }
      return salida
    }
    const porOF = new Map<number, Asignacion[]>()
    for (const a of asignaciones) porOF.set(a.of_id, [...(porOF.get(a.of_id) ?? []), a])
    return [...porOF.values()]
      .map((items) => {
        const a = items[0]
        return { clave: `of${a.of_id}`, etiqueta: `OF ${a.of}`, sub: `${a.seccion ?? ''} · ${a.grupo_hf ?? a.tipo}`, grupo: `Tanda ${a.tanda ?? '—'} · ${a.aparato ?? 'varios aparatos'}`, items }
      })
      .sort((x, y) => (x.grupo === y.grupo ? new Date(x.items[0].inicio).getTime() - new Date(y.items[0].inicio).getTime() : x.grupo.localeCompare(y.grupo)))
  }, [asignaciones, recursos, vista])

  const grupos = useMemo(() => {
    const g: { nombre: string; filas: Fila[] }[] = []
    for (const f of filas) {
      if (!g.length || g[g.length - 1].nombre !== f.grupo) g.push({ nombre: f.grupo, filas: [] })
      g[g.length - 1].filas.push(f)
    }
    return g
  }, [filas])

  const ancho = (t1 - t0) * px
  const x = (iso: string | number) => (new Date(iso).getTime() - t0) * px

  const dias: { x: number; txt: string }[] = []
  for (let t = t0; t < t1; t += 86400000) dias.push({ x: x(t), txt: fecha(new Date(t).toISOString()).slice(0, 9) })
  const paso = zoom === 'hora' ? 1 : zoom === 'turno' ? 4 : 12
  const marcas: { x: number; txt: string }[] = []
  for (let t = t0; t < t1; t += paso * 3600000) marcas.push({ x: x(t), txt: hora(new Date(t).toISOString()) })

  const empezar = (e: RMouseEvent, a: Asignacion) => {
    if (!onMover || a.bloqueada) return
    e.preventDefault()
    movido.current = false
    const x0 = e.clientX
    setArrastre({ id: a.operacion_id, x0, dx: 0 })
    const mover = (ev: MouseEvent) => {
      if (Math.abs(ev.clientX - x0) > 3) movido.current = true
      setArrastre({ id: a.operacion_id, x0, dx: ev.clientX - x0 })
    }
    const soltar = (ev: MouseEvent) => {
      window.removeEventListener('mousemove', mover)
      window.removeEventListener('mouseup', soltar)
      setArrastre(null)
      const dx = ev.clientX - x0
      if (Math.abs(dx) > 3) {
        const deltaMin = Math.round(dx / px / 60000 / SNAP_MIN) * SNAP_MIN
        if (deltaMin !== 0) onMover(a, new Date(new Date(a.inicio).getTime() + deltaMin * 60000))
      }
    }
    window.addEventListener('mousemove', mover)
    window.addEventListener('mouseup', soltar)
  }

  return (
    <div className="gantt">
      <div className="gantt-interior" style={{ width: ANCHO_ETQ + ancho }}>
        <div className="gantt-cab" style={{ width: ANCHO_ETQ + ancho }}>
          <div className="gantt-etq" style={{ position: 'absolute', left: 0, top: 0, height: 44, fontWeight: 700 }}>
            {vista === 'recurso' ? 'Recurso' : 'OF'}
          </div>
          {dias.map((d) => (
            <div key={d.x} style={{ position: 'absolute', left: ANCHO_ETQ + d.x, top: 4, fontSize: 12, fontWeight: 700, borderLeft: '1px solid var(--borde)', paddingLeft: 4 }}>
              {d.txt}
            </div>
          ))}
          {marcas.map((m) => (
            <div key={m.x} style={{ position: 'absolute', left: ANCHO_ETQ + m.x, top: 24, fontSize: 10, color: 'var(--texto-3)', paddingLeft: 2, borderLeft: '1px solid var(--borde)', height: 20 }}>
              {m.txt}
            </div>
          ))}
        </div>
        <div style={{ position: 'relative' }}>
          <div style={{ position: 'absolute', left: ANCHO_ETQ, top: 0, bottom: 0, width: ancho, pointerEvents: 'none' }}>
            {turnos.map((t, i) => (
              <div key={i} className="gantt-turno" style={{ left: x(t.inicio), width: x(t.fin) - x(t.inicio) }} title={`Turno ${t.turno}`} />
            ))}
            <div className="gantt-ahora" style={{ left: x(ahora) }} title={`Ahora ${fecha(ahora)}`} />
          </div>
          {grupos.map((g) => (
            <div key={g.nombre}>
              <div className="gantt-grupo" style={{ width: ANCHO_ETQ + ancho }}>
                {g.nombre}
              </div>
              {g.filas.map((f) => (
                <div key={f.clave} className="gantt-fila" style={{ height: ALTO_FILA, width: ANCHO_ETQ + ancho }}>
                  <div className="gantt-etq" title={f.sub}>
                    <strong>{f.etiqueta}</strong> <span className="tenue">{f.sub}</span>
                  </div>
                  {f.items.map((a) => {
                    const dx = arrastre?.id === a.operacion_id ? arrastre.dx : 0
                    const tramos = a.tramos && a.tramos.length ? a.tramos : ([[a.inicio, a.fin]] as [string, string][])
                    const clases = `barra ${a.riesgo} ${a.provisional ? 'provisional' : ''} ${a.bloqueada ? 'bloqueada' : ''} ${seleccion === a.operacion_id ? 'seleccionada' : ''} ${dx ? 'arrastrando' : ''}`
                    const titulo = `OF ${a.of} · ${a.tipo}\n${a.recurso ?? ''}${a.operario ? ' · ' + a.operario : ''}\n${fecha(a.inicio)} → ${fecha(a.fin)} (${a.minutos} min)\nTanda ${a.tanda ?? '—'} · ${a.aparato ?? ''}\nPrioridad ${a.prioridad ?? '—'}${a.provisional ? '\nPROVISIONAL: pendiente de programación' : ''}${a.bloqueada ? '\nBLOQUEADA por el usuario' : ''}`
                    return tramos.map(([ini, fin], k) => (
                      <div
                        key={`${a.operacion_id}-${k}`}
                        className={clases}
                        style={{ left: ANCHO_ETQ + x(ini) + dx, width: Math.max(3, x(fin) - x(ini)), top: 4 }}
                        title={titulo}
                        onMouseDown={(e) => empezar(e, a)}
                        onClick={() => {
                          if (!movido.current) onSeleccionar(a)
                        }}
                      >
                        {k === 0 && (vista === 'recurso' ? `${a.of} ${a.tipo}` : `${a.tipo} · ${a.recurso ?? ''}`)}
                      </div>
                    ))
                  })}
                </div>
              ))}
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}
