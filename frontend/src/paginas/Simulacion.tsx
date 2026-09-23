import { useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { api, puede } from '../api'
import { useSesion } from '../App'
import { Cargando, MensajeError, Riesgo, useDatos } from '../componentes/comunes'
import { fecha, horas, minutos, pct } from '../formato'
import type { Kpis, Nivel, OFResumen, ResultadoReplan } from '../tipos'
import { TablaCambios } from './ControlTower'

interface ResUrgente extends ResultadoReplan {
  simulacion_id: number
  of: string
  texto: string
  of_urgente_planificada: { inicio: string; fin: string; recurso: string | null }[]
}

interface ResWhatIf {
  escenario: string[]
  kpis_base: Kpis
  kpis_simulado: Kpis
  tandas: { tanda: string; riesgo_base: Nivel | null; riesgo_simulado: Nivel; fin_base: string | null; fin_simulado: string | null; motivos: string[] }[]
  aparatos: { aparato: string; riesgo_base: Nivel | null; riesgo_simulado: Nivel; fin_base: string | null; fin_simulado: string | null; holgura_base_h: number | null; holgura_simulada_h: number | null }[]
  cambios: { of: string; operacion_id: number; antes_fin: string | null; despues_fin: string; impacto_min: number | null }[]
  operaciones_que_salen_del_plan: { of: string; tipo: string; detalle: string }[]
  simulacion_id?: number
}

export default function Simulacion() {
  const [params] = useSearchParams()
  const [pestana, setPestana] = useState(params.get('of') ? 'urgente' : 'whatif')
  return (
    <>
      <div className="cabecera">
        <div>
          <h1>Simulación</h1>
          <div className="sub">Las simulaciones trabajan sobre una copia: nunca modifican el plan real salvo que un responsable acepte el resultado.</div>
        </div>
      </div>
      <div className="pestanas">
        <button className={pestana === 'whatif' ? 'activa' : ''} onClick={() => setPestana('whatif')}>
          ¿Qué pasa si…?
        </button>
        <button className={pestana === 'urgente' ? 'activa' : ''} onClick={() => setPestana('urgente')}>
          Introducir OF urgente
        </button>
        <button className={pestana === 'comparar' ? 'activa' : ''} onClick={() => setPestana('comparar')}>
          Comparar simulaciones
        </button>
      </div>
      {pestana === 'whatif' ? <WhatIf /> : pestana === 'comparar' ? <Comparador /> : <OFUrgente ofInicial={params.get('of')} />}
    </>
  )
}

function OFUrgente({ ofInicial }: { ofInicial: string | null }) {
  const { sesion } = useSesion()
  const [numero, setNumero] = useState('')
  const [motivo, setMotivo] = useState('')
  const [res, setRes] = useState<ResUrgente | null>(null)
  const [decision, setDecision] = useState<string | null>(null)
  const [err, setErr] = useState<unknown>(null)
  const [cargando, setCargando] = useState(false)
  const inicial = useDatos(() => (ofInicial ? api.get<OFResumen>(`/ofs/${ofInicial}`) : Promise.resolve(null)), [ofInicial])
  const simular = async () => {
    setErr(null)
    setRes(null)
    setDecision(null)
    setCargando(true)
    try {
      let id = inicial.datos && (!numero || numero === inicial.datos.numero) ? inicial.datos.id : null
      if (!id) {
        const r = await api.get<{ items: OFResumen[] }>(`/ofs?q=${encodeURIComponent(numero)}`)
        id = r.items.find((o) => o.numero === numero)?.id ?? null
        if (!id) throw new Error(`OF ${numero} no encontrada`)
      }
      setRes(await api.post<ResUrgente>('/plan/simulaciones/of-urgente', { of_id: id, motivo: motivo || null }))
    } catch (e) {
      setErr(e)
    } finally {
      setCargando(false)
    }
  }
  return (
    <>
      <section className="panel">
        <p className="tenue">
          Nunca se introduce una OF urgente destruyendo el plan: primero se calcula su duración, recursos, las OF que habría que desplazar y el riesgo que se genera. Después el responsable
          acepta o rechaza.
        </p>
        <div className="formulario">
          <label className="campo">
            Nº de OF
            <input value={numero || inicial.datos?.numero || ''} onChange={(e) => setNumero(e.target.value.trim())} />
          </label>
          <label className="campo">
            Motivo
            <input value={motivo} onChange={(e) => setMotivo(e.target.value)} placeholder="Cliente adelanta la entrega" />
          </label>
          <button className="primario" onClick={simular} disabled={cargando || !puede(sesion, 'modificar_plan')}>
            {cargando ? 'Calculando…' : 'Calcular impacto'}
          </button>
        </div>
        <MensajeError error={err} />
      </section>
      {res && (
        <section className="panel">
          <h2>{res.texto}</h2>
          {res.of_urgente_planificada.length > 0 && (
            <p>
              La OF {res.of} quedaría: {res.of_urgente_planificada.map((p) => `${fecha(p.inicio)} → ${fecha(p.fin)} en ${p.recurso}`).join(' · ')}
            </p>
          )}
          {res.tandas.map((t) => (
            <p key={t.tanda}>
              Riesgo TANDA {t.tanda}: <Riesgo nivel={t.riesgo_antes} /> → <Riesgo nivel={t.riesgo_despues} />
            </p>
          ))}
          <TablaCambios cambios={res.cambios} />
          {decision ? (
            <div className="mensaje ok">{decision}</div>
          ) : (
            <div className="botones" style={{ marginTop: 12 }}>
              <button
                className="primario"
                onClick={async () => {
                  try {
                    await api.post(`/plan/simulaciones/${res.simulacion_id}/decidir`, { aceptar: true, motivo })
                    setDecision('Aceptada: el plan oficial se ha actualizado y se ha avisado a los operarios afectados.')
                  } catch (e) {
                    setErr(e)
                  }
                }}
              >
                Aceptar
              </button>
              <button
                className="peligro"
                onClick={async () => {
                  await api.post(`/plan/simulaciones/${res.simulacion_id}/decidir`, { aceptar: false, motivo })
                  setDecision('Rechazada: el plan oficial no cambia. La simulación queda registrada.')
                }}
              >
                Rechazar
              </button>
            </div>
          )}
        </section>
      )}
    </>
  )
}

/** Un escenario se puede «aplicar» si solo contiene decisiones (no supuestos como averías). */
function esDecision(esc: Record<string, unknown>): boolean {
  const supuestos = ['averias', 'ausencias', 'faltan_operarios', 'falta_material', 'retrasos', 'recursos_extra']
  const tiene = (k: string) => Array.isArray(esc[k]) && (esc[k] as unknown[]).length > 0
  return !supuestos.some(tiene) && (tiene('turnos_extra') || tiene('adelantar_of'))
}

function WhatIf() {
  const { sesion } = useSesion()
  const recursos = useDatos(() => api.get<{ id: number; codigo: string; seccion: string | null }[]>('/recursos'), [])
  const [averiaRec, setAveriaRec] = useState('')
  const [averiaH, setAveriaH] = useState('4')
  const [faltanSec, setFaltanSec] = useState('')
  const [faltanN, setFaltanN] = useState('2')
  const [adelantar, setAdelantar] = useState('')
  const [extraRec, setExtraRec] = useState('')
  const [extraFecha, setExtraFecha] = useState('')
  const [extraTurno, setExtraTurno] = useState('')
  const [extraSeccion, setExtraSeccion] = useState('')
  const turnos = useDatos(() => api.get<{ codigo: string; nombre: string; activo: boolean }[]>('/turnos'), [])
  const [modo, setModo] = useState('incremental')
  const [res, setRes] = useState<ResWhatIf | null>(null)
  const [ultimo, setUltimo] = useState<Record<string, unknown> | null>(null)
  const [aplicado, setAplicado] = useState<{ aplicado: string[]; kpis?: { planificadas: number } } | null>(null)
  const [motivoAplicar, setMotivoAplicar] = useState('')
  const [err, setErr] = useState<unknown>(null)
  const [cargando, setCargando] = useState(false)
  const secciones = [...new Set((recursos.datos ?? []).map((r) => r.seccion).filter(Boolean))] as string[]
  const simular = async () => {
    setErr(null)
    setRes(null)
    setCargando(true)
    try {
      const esc: Record<string, unknown> = { modo, nombre: 'What-if' }
      if (averiaRec) esc.averias = [{ recurso_id: Number(averiaRec), horas: Number(averiaH) }]
      if (faltanSec) esc.faltan_operarios = [{ seccion: faltanSec, cantidad: Number(faltanN) }]
      if (extraRec) esc.recursos_extra = [{ clonar_recurso_id: Number(extraRec), cantidad: 1 }]
      if (extraFecha) esc.turnos_extra = [{ fecha: extraFecha, turno: extraTurno || turnos.datos?.[0]?.codigo, secciones: extraSeccion ? [extraSeccion] : null }]
      if (adelantar) {
        const ids: number[] = []
        for (const n of adelantar.split(/[ ,;]+/).filter(Boolean)) {
          const r = await api.get<{ items: OFResumen[] }>(`/ofs?q=${n}`)
          const of = r.items.find((o) => o.numero === n)
          if (!of) throw new Error(`OF ${n} no encontrada`)
          ids.push(of.id)
        }
        esc.adelantar_of = ids
      }
      setAplicado(null)
      setRes(await api.post<ResWhatIf>('/plan/simulaciones/escenario', { escenario: esc, guardar: true }))
      setUltimo(esc)
    } catch (e) {
      setErr(e)
    } finally {
      setCargando(false)
    }
  }
  return (
    <>
      <section className="panel">
        <div className="formulario">
          <label className="campo">
            ¿Y si se avería…?
            <select value={averiaRec} onChange={(e) => setAveriaRec(e.target.value)}>
              <option value="">— ninguna máquina —</option>
              {(recursos.datos ?? []).map((r) => (
                <option key={r.id} value={r.id}>
                  {r.codigo}
                </option>
              ))}
            </select>
          </label>
          <label className="campo">
            …durante (horas)
            <input type="number" value={averiaH} onChange={(e) => setAveriaH(e.target.value)} />
          </label>
          <label className="campo">
            ¿Y si faltan operarios en la sección…?
            <select value={faltanSec} onChange={(e) => setFaltanSec(e.target.value)}>
              <option value="">—</option>
              {secciones.map((s) => (
                <option key={s}>{s}</option>
              ))}
            </select>
          </label>
          <label className="campo">
            …cuántos
            <input type="number" value={faltanN} onChange={(e) => setFaltanN(e.target.value)} />
          </label>
          <label className="campo">
            ¿Y si adelanto estas OF? (nº separados por comas)
            <input value={adelantar} onChange={(e) => setAdelantar(e.target.value)} />
          </label>
          <label className="campo">
            ¿Y si tuviera otra máquina como…?
            <select value={extraRec} onChange={(e) => setExtraRec(e.target.value)}>
              <option value="">—</option>
              {(recursos.datos ?? []).map((r) => (
                <option key={r.id} value={r.id}>
                  {r.codigo}
                </option>
              ))}
            </select>
          </label>
          <label className="campo">
            ¿Y si hago un turno extra el día…?
            <input id="extra-fecha" type="date" value={extraFecha} onChange={(e) => setExtraFecha(e.target.value)} />
          </label>
          <label className="campo">
            …en el turno
            <select id="extra-turno" value={extraTurno} onChange={(e) => setExtraTurno(e.target.value)}>
              {(turnos.datos ?? [])
                .filter((t) => t.activo)
                .map((t) => (
                  <option key={t.codigo} value={t.codigo}>
                    {t.nombre}
                  </option>
                ))}
            </select>
          </label>
          <label className="campo">
            …para
            <select id="extra-seccion" value={extraSeccion} onChange={(e) => setExtraSeccion(e.target.value)}>
              <option value="">toda la fábrica</option>
              {secciones.map((s) => (
                <option key={s} value={s}>
                  la sección {s}
                </option>
              ))}
            </select>
          </label>
          <label className="campo">
            Modo
            <select value={modo} onChange={(e) => setModo(e.target.value)}>
              <option value="incremental">Incremental (congela el plan actual)</option>
              <option value="completo">Replanificación completa</option>
            </select>
          </label>
          <button className="primario" onClick={simular} disabled={cargando}>
            {cargando ? 'Simulando…' : 'Simular'}
          </button>
        </div>
        <p className="pequeno tenue">
          Para «¿qué pasa si incorporo esta tanda?», impórtala y exclúyela del plan desde su ficha; luego inclúyela aquí o genera el plan con ella.
        </p>
        <MensajeError error={err} />
      </section>
      {cargando && <Cargando />}
      {res && (
        <>
          {ultimo && esDecision(ultimo) && puede(sesion, 'planificar') && (
            <section className="panel destacado">
              <h2>¿Lo hacemos de verdad?</h2>
              {aplicado ? (
                <div className="mensaje ok">
                  Aplicado: {aplicado.aplicado.join(', ')}. Plan oficial regenerado{aplicado.kpis ? ` (${aplicado.kpis.planificadas} operaciones planificadas)` : ''}.{' '}
                  <Link to="/gantt">Ver el Gantt</Link>
                </div>
              ) : (
                <>
                  <p className="pequeno tenue">
                    Este escenario solo contiene decisiones que dependen de la planta (turnos extra, OF adelantadas). Aplicarlo las registra en el calendario y en las OF, y regenera el plan
                    oficial. Queda auditado.
                  </p>
                  <div className="botones">
                    <input id="motivo-aplicar" placeholder="Motivo (p. ej. recuperar la semana 40)" value={motivoAplicar} onChange={(e) => setMotivoAplicar(e.target.value)} style={{ minWidth: 280 }} />
                    <button
                      className="primario"
                      disabled={!motivoAplicar.trim()}
                      onClick={async () => {
                        setErr(null)
                        try {
                          setAplicado(await api.post('/plan/simulaciones/escenario/aplicar', { escenario: ultimo, motivo: motivoAplicar }))
                        } catch (e) {
                          setErr(e)
                        }
                      }}
                    >
                      Aplicar y replanificar
                    </button>
                  </div>
                </>
              )}
            </section>
          )}
          <section className="panel">
            <h2>Escenario: {res.escenario.join(' · ') || 'sin cambios'}</h2>
            <table>
              <thead>
                <tr>
                  <th>Indicador</th>
                  <th className="num">PLAN ACTUAL</th>
                  <th className="num">PLAN SIMULADO</th>
                </tr>
              </thead>
              <tbody>
                <tr><td>Operaciones planificadas</td><td className="num">{res.kpis_base.planificadas}</td><td className="num">{res.kpis_simulado.planificadas}</td></tr>
                <tr><td>No planificables</td><td className="num">{res.kpis_base.no_planificadas}</td><td className="num">{res.kpis_simulado.no_planificadas}</td></tr>
                <tr><td>Fin del plan</td><td className="num">{fecha(res.kpis_base.fin_plan)}</td><td className="num">{fecha(res.kpis_simulado.fin_plan)}</td></tr>
                <tr><td>Cumplimiento de semana</td><td className="num">{pct(res.kpis_base.cumplimiento_semana)}</td><td className="num">{pct(res.kpis_simulado.cumplimiento_semana)}</td></tr>
                <tr><td>Retraso total</td><td className="num">{horas(res.kpis_base.retraso_total_h)}</td><td className="num">{horas(res.kpis_simulado.retraso_total_h)}</td></tr>
                <tr><td>Cambios de setup</td><td className="num">{res.kpis_base.cambios_setup}</td><td className="num">{res.kpis_simulado.cambios_setup}</td></tr>
                <tr><td>Recursos críticos</td><td className="num">{res.kpis_base.recursos_criticos.join(', ') || '—'}</td><td className="num">{res.kpis_simulado.recursos_criticos.join(', ') || '—'}</td></tr>
              </tbody>
            </table>
          </section>
          <div className="rejilla dos">
            <section className="panel">
              <h2>Tandas y aparatos</h2>
              <table>
                <thead>
                  <tr>
                    <th />
                    <th>Riesgo actual</th>
                    <th>Riesgo simulado</th>
                    <th>Fin actual</th>
                    <th>Fin simulado</th>
                  </tr>
                </thead>
                <tbody>
                  {res.tandas.map((t) => (
                    <tr key={t.tanda}>
                      <td><strong>Tanda {t.tanda}</strong></td>
                      <td><Riesgo nivel={t.riesgo_base} /></td>
                      <td><Riesgo nivel={t.riesgo_simulado} /></td>
                      <td className="pequeno">{fecha(t.fin_base)}</td>
                      <td className="pequeno">{fecha(t.fin_simulado)}</td>
                    </tr>
                  ))}
                  {res.aparatos.map((a) => (
                    <tr key={a.aparato}>
                      <td>{a.aparato}</td>
                      <td><Riesgo nivel={a.riesgo_base} /></td>
                      <td><Riesgo nivel={a.riesgo_simulado} /></td>
                      <td className="pequeno">{fecha(a.fin_base)}</td>
                      <td className="pequeno">{fecha(a.fin_simulado)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </section>
            <section className="panel">
              <h2>OF que cambian ({res.cambios.length})</h2>
              <table>
                <thead>
                  <tr>
                    <th>OF</th>
                    <th>Fin actual</th>
                    <th>Fin simulado</th>
                    <th className="num">Impacto</th>
                  </tr>
                </thead>
                <tbody>
                  {res.cambios.slice(0, 40).map((c) => (
                    <tr key={c.operacion_id}>
                      <td>{c.of}</td>
                      <td className="pequeno">{fecha(c.antes_fin)}</td>
                      <td className="pequeno">{fecha(c.despues_fin)}</td>
                      <td className="num">{minutos(c.impacto_min)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
              {res.operaciones_que_salen_del_plan.length > 0 && (
                <div className="mensaje error">
                  Salen del plan: {res.operaciones_que_salen_del_plan.map((n) => `OF ${n.of} ${n.tipo}`).join(', ')}
                </div>
              )}
              {res.simulacion_id && <p className="pequeno tenue">Guardada como simulación #{res.simulacion_id} (no afecta al plan real).</p>}
            </section>
          </div>
        </>
      )}
      <p className="pequeno">
        <Link to="/incidencias">¿La avería es real? Regístrala como incidencia para replanificar el plan oficial.</Link>
      </p>
    </>
  )
}

interface SimGuardada {
  id: number
  nombre: string
  estado: string
  creado: string
  creado_por: string
  motivo: string | null
  kpis: Kpis | null
}

const INDICADORES: { clave: keyof Kpis; texto: string; mejor: 'mas' | 'menos'; ver: (k: Kpis) => string }[] = [
  { clave: 'planificadas', texto: 'Operaciones planificadas', mejor: 'mas', ver: (k) => String(k.planificadas) },
  { clave: 'no_planificadas', texto: 'No planificables', mejor: 'menos', ver: (k) => String(k.no_planificadas) },
  { clave: 'cumplimiento_semana', texto: 'Cumplimiento de semana', mejor: 'mas', ver: (k) => pct(k.cumplimiento_semana) },
  { clave: 'aparatos_en_plazo', texto: 'Aparatos en plazo', mejor: 'mas', ver: (k) => `${k.aparatos_en_plazo} / ${k.aparatos_evaluados}` },
  { clave: 'retraso_total_h', texto: 'Retraso total', mejor: 'menos', ver: (k) => horas(k.retraso_total_h) },
  { clave: 'fin_plan', texto: 'Fin del plan', mejor: 'menos', ver: (k) => fecha(k.fin_plan) },
  { clave: 'cambios_setup', texto: 'Cambios de setup', mejor: 'menos', ver: (k) => String(k.cambios_setup) },
  { clave: 'horas_muertas', texto: 'Horas muertas', mejor: 'menos', ver: (k) => horas(k.horas_muertas) },
  { clave: 'utilizacion_media', texto: 'Utilización media', mejor: 'mas', ver: (k) => pct(k.utilizacion_media) },
]

const valorNum = (k: Kpis, c: keyof Kpis) => {
  const v = k[c]
  if (typeof v === 'number') return v
  if (typeof v === 'string') return new Date(v).getTime()
  return null
}

/** Pone varias simulaciones guardadas junto al plan actual y marca la mejor en cada indicador. */
function Comparador() {
  const sims = useDatos(() => api.get<SimGuardada[]>('/plan/simulaciones'), [])
  const activo = useDatos(() => api.get<{ plan_id: number | null; nombre?: string; kpis?: Kpis }>('/plan/activo'), [])
  const [elegidas, setElegidas] = useState<number[]>([])
  if (sims.error) return <MensajeError error={sims.error} />
  if (!sims.datos || !activo.datos) return <Cargando />
  const conKpis = sims.datos.filter((s) => s.kpis)
  const columnas: { id: string; titulo: string; sub: string; kpis: Kpis }[] = []
  if (activo.datos.kpis) columnas.push({ id: 'actual', titulo: 'Plan actual', sub: activo.datos.nombre ?? '', kpis: activo.datos.kpis })
  for (const id of elegidas) {
    const s = conKpis.find((x) => x.id === id)
    if (s?.kpis) columnas.push({ id: String(s.id), titulo: `#${s.id} ${s.nombre}`, sub: s.motivo ?? '', kpis: s.kpis })
  }
  const alternar = (id: number) => setElegidas((e) => (e.includes(id) ? e.filter((x) => x !== id) : [...e, id].slice(-4)))
  return (
    <>
      <section className="panel">
        <h2>Simulaciones guardadas</h2>
        {conKpis.length === 0 ? (
          <p className="tenue">Aún no hay simulaciones. Haz alguna en «¿Qué pasa si…?» o «Introducir OF urgente» y vuelve aquí para compararlas.</p>
        ) : (
          <>
            <p className="pequeno tenue">Elige hasta 4 para ponerlas junto al plan actual.</p>
            <table>
              <tbody>
                {conKpis.map((s) => (
                  <tr key={s.id} className={elegidas.includes(s.id) ? 'fila-elegida' : ''}>
                    <td style={{ width: 30 }}>
                      <input type="checkbox" aria-label={`Comparar simulación ${s.id}`} checked={elegidas.includes(s.id)} onChange={() => alternar(s.id)} />
                    </td>
                    <td>
                      <strong>
                        #{s.id} {s.nombre}
                      </strong>
                      <div className="pequeno tenue">{s.motivo}</div>
                    </td>
                    <td className="pequeno">
                      {fecha(s.creado)} · {s.creado_por}
                    </td>
                    <td>
                      <span className="etiqueta">{s.estado === 'BORRADOR' ? 'sin decidir' : s.estado.toLowerCase()}</span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </>
        )}
      </section>
      {columnas.length > 1 && (
        <section className="panel">
          <h2>Comparativa</h2>
          <div className="tabla-desplazable">
            <table className="comparativa">
              <thead>
                <tr>
                  <th>Indicador</th>
                  {columnas.map((c) => (
                    <th key={c.id} className="num" title={c.sub}>
                      {c.titulo}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {INDICADORES.map((ind) => {
                  const vals = columnas.map((c) => valorNum(c.kpis, ind.clave))
                  const validos = vals.filter((v): v is number => v != null)
                  const mejor = validos.length > 1 && new Set(validos).size > 1 ? (ind.mejor === 'mas' ? Math.max(...validos) : Math.min(...validos)) : null
                  return (
                    <tr key={ind.clave}>
                      <td>{ind.texto}</td>
                      {columnas.map((c, i) => (
                        <td key={c.id} className={`num ${mejor != null && vals[i] === mejor ? 'mejor' : ''}`}>
                          {ind.ver(c.kpis)}
                        </td>
                      ))}
                    </tr>
                  )
                })}
                <tr>
                  <td>Recursos críticos</td>
                  {columnas.map((c) => (
                    <td key={c.id} className="num pequeno">
                      {c.kpis.recursos_criticos?.join(', ') || '—'}
                    </td>
                  ))}
                </tr>
              </tbody>
            </table>
          </div>
          <p className="pequeno tenue">En verde, el mejor valor de cada fila. Para aplicar una simulación, repítela en «¿Qué pasa si…?» y pulsa «Aplicar y replanificar».</p>
        </section>
      )}
    </>
  )
}
