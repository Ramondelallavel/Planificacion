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
      </div>
      {pestana === 'whatif' ? <WhatIf /> : <OFUrgente ofInicial={params.get('of')} />}
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

function WhatIf() {
  const recursos = useDatos(() => api.get<{ id: number; codigo: string; seccion: string | null }[]>('/recursos'), [])
  const [averiaRec, setAveriaRec] = useState('')
  const [averiaH, setAveriaH] = useState('4')
  const [faltanSec, setFaltanSec] = useState('')
  const [faltanN, setFaltanN] = useState('2')
  const [adelantar, setAdelantar] = useState('')
  const [extraRec, setExtraRec] = useState('')
  const [modo, setModo] = useState('incremental')
  const [res, setRes] = useState<ResWhatIf | null>(null)
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
      setRes(await api.post<ResWhatIf>('/plan/simulaciones/escenario', { escenario: esc, guardar: true }))
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
