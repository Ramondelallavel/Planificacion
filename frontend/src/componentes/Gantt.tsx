import { useMemo, useRef, useState, type MouseEvent as RMouseEvent } from 'react'
import { fecha, hora } from '../formato'
import type { Asignacion, RecursoGantt } from '../tipos'

export type Zoom = 'hora' | 'turno' | 'dia' | 'semana'
export type Vista = 'recurso' | 'tanda' | 'operario'

export interface OperarioGantt {
  id: number
  codigo: string
  nombre: string
  turno: string | null
}

const PX_HORA: Record<Zoom, number> = { hora: 70, turno: 22, dia: 7, semana: 2.6 }
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
  operarios?: OperarioGantt[]
  turnos: { turno: string; inicio: string; fin: string; extra?: boolean }[]
  limites?: { semana: string; fecha: string }[]
  ahora: string
  zoom: Zoom
  vista: Vista
  seleccion: number | null
  /** operaciones a destacar (cadena de dependencias); el resto se atenúa */
  resaltadas?: Set<number> | null
  /** mostrar solo las filas que tienen trabajo */
  soloConCarga?: boolean
  onSeleccionar: (a: Asignacion) => void
  onMover?: (a: Asignacion, nuevoInicio: Date) => void
}

export default function Gantt({ asignaciones, recursos, operarios = [], turnos, limites = [], ahora, zoom, vista, seleccion, resaltadas, soloConCarga, onSeleccionar, onMover }: Props) {
  const px = PX_HORA[zoom] / 3600000
  const [arrastre, setArrastre] = useState<{ id: number; x0: number; dx: number } | null>(null)
  const movido = useRef(false)

  const { t0, t1 } = useMemo(() => {
    const ahoraMs = new Date(ahora).getTime()
    const ini = Math.min(ahoraMs - 2 * 3600000, ...asignaciones.map((a) => new Date(a.inicio).getTime()))
    const fin = Math.max(ahoraMs + 24 * 3600000, ...asignaciones.map((a) => new Date(a.fin).getTime()), ...limites.map((l) => new Date(l.fecha).getTime() + 3600000))
    const d0 = new Date(ini)
    d0.setHours(0, 0, 0, 0)
    const d1 = new Date(fin)
    d1.setHours(24, 0, 0, 0)
    return { t0: d0.getTime(), t1: d1.getTime() }
  }, [asignaciones, ahora, limites])

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
          if (soloConCarga && !items.length) continue
          salida.push({ clave: `${r.id}:${u}`, etiqueta: r.capacidad > 1 ? `${r.codigo} #${u + 1}` : r.codigo, sub: r.estado !== 'OPERATIVO' ? r.estado : r.nombre, grupo: r.seccion ?? '—', items })
        }
      }
      return salida
    }
    if (vista === 'operario') {
      const porOpr = new Map<number, Asignacion[]>()
      const sinOperario: Asignacion[] = []
      for (const a of asignaciones) {
        if (a.operario_id == null) sinOperario.push(a)
        else porOpr.set(a.operario_id, [...(porOpr.get(a.operario_id) ?? []), a])
      }
      const salida: Fila[] = operarios
        .filter((o) => !soloConCarga || porOpr.has(o.id))
        .map((o) => ({ clave: `o${o.id}`, etiqueta: o.nombre, sub: o.codigo, grupo: `Turno ${o.turno ?? '—'}`, items: porOpr.get(o.id) ?? [] }))
        .sort((x, y) => x.grupo.localeCompare(y.grupo))
      if (sinOperario.length) salida.push({ clave: 'sin', etiqueta: 'Sin operario', sub: 'recursos automáticos', grupo: 'Otros', items: sinOperario })
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
  }, [asignaciones, recursos, operarios, vista, soloConCarga])

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
  for (let t = t0; t < t1; t += 86400000) dias.push({ x: x(t), txt: zoom === 'semana' ? fecha(new Date(t).toISOString()).slice(4, 9) : fecha(new Date(t).toISOString()).slice(0, 9) })
  const paso = zoom === 'hora' ? 1 : zoom === 'turno' ? 4 : zoom === 'dia' ? 12 : 0
  const marcas: { x: number; txt: string }[] = []
  if (paso) for (let t = t0; t < t1; t += paso * 3600000) marcas.push({ x: x(t), txt: hora(new Date(t).toISOString()) })

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

  const textoBarra = (a: Asignacion) => (vista === 'recurso' ? `${a.of} ${a.tipo}` : vista === 'operario' ? `${a.of} ${a.tipo} · ${a.recurso ?? ''}` : `${a.tipo} · ${a.recurso ?? ''}`)

  return (
    <div className="gantt">
      <div className="gantt-interior" style={{ width: ANCHO_ETQ + ancho }}>
        <div className="gantt-cab" style={{ width: ANCHO_ETQ + ancho }}>
          <div className="gantt-etq" style={{ position: 'absolute', left: 0, top: 0, height: 44, fontWeight: 700 }}>
            {vista === 'recurso' ? 'Recurso' : vista === 'operario' ? 'Operario' : 'OF'}
          </div>
          {dias.map((d) => (
            <div key={d.x} className="gantt-dia" style={{ left: ANCHO_ETQ + d.x }}>
              {d.txt}
            </div>
          ))}
          {marcas.map((m) => (
            <div key={m.x} className="gantt-marca" style={{ left: ANCHO_ETQ + m.x }}>
              {m.txt}
            </div>
          ))}
        </div>
        <div style={{ position: 'relative' }}>
          <div style={{ position: 'absolute', left: ANCHO_ETQ, top: 0, bottom: 0, width: ancho, pointerEvents: 'none' }}>
            {turnos.map((t, i) => (
              <div key={i} className={`gantt-turno ${t.extra ? 'extra' : ''}`} style={{ left: x(t.inicio), width: x(t.fin) - x(t.inicio) }} title={`Turno ${t.turno}${t.extra ? ' · jornada extra' : ''}`} />
            ))}
            {limites.map((l) => (
              <div key={l.semana} className="gantt-limite" style={{ left: x(l.fecha) }} title={`Límite de la semana de fabricación ${l.semana}: ${fecha(l.fecha)}`}>
                <span>Límite {l.semana.slice(4)}</span>
              </div>
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
                    const atenuada = resaltadas ? !resaltadas.has(a.operacion_id) : false
                    const clases = `barra ${a.riesgo} ${a.provisional ? 'provisional' : ''} ${a.bloqueada ? 'bloqueada' : ''} ${seleccion === a.operacion_id ? 'seleccionada' : ''} ${dx ? 'arrastrando' : ''} ${atenuada ? 'atenuada' : ''} ${resaltadas && !atenuada ? 'en-cadena' : ''} ${a.urgente ? 'urgente' : ''}`
                    const titulo = `OF ${a.of} · ${a.tipo}\n${a.recurso ?? ''}${a.operario ? ' · ' + a.operario : ''}\n${fecha(a.inicio)} → ${fecha(a.fin)} (${a.minutos} min)\nTanda ${a.tanda ?? '—'} · ${a.aparato ?? ''}\nPrioridad ${a.prioridad ?? '—'}${a.urgente ? '\nURGENTE' : ''}${a.provisional ? '\nPROVISIONAL: pendiente de programación' : ''}${a.bloqueada ? '\nBLOQUEADA por el usuario' : ''}`
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
                        {k === 0 && zoom !== 'semana' && textoBarra(a)}
                      </div>
                    ))
                  })}
                </div>
              ))}
            </div>
          ))}
          {!grupos.length && <div className="tenue" style={{ padding: 16 }}>Nada que mostrar con estos filtros.</div>}
        </div>
      </div>
    </div>
  )
}
