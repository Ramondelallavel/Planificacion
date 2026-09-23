import { useState } from 'react'
import { api, puede } from '../api'
import { useSesion } from '../App'
import { Cargando, MensajeError, Riesgo, useDatos } from '../componentes/comunes'
import { fecha, fecha as f2, isoLocal } from '../formato'
import type { OFResumen, ResultadoReplan } from '../tipos'
import { TablaCambios } from './ControlTower'

interface Inc {
  id: number
  tipo: string
  descripcion: string
  recurso: string | null
  operario: string | null
  of_id: number | null
  inicio: string
  fin_prevista: string | null
  fin: string | null
  estado: string
  reportado_por: string | null
  impacto: { resumen: string; cambios: number } | null
}

const TIPOS: [string, string][] = [
  ['AVERIA', 'Avería de máquina'],
  ['AUSENCIA', 'Ausencia de trabajador'],
  ['FALTA_MATERIAL', 'Falta de material'],
  ['RETRASO', 'Operación más lenta / retraso'],
  ['CAMBIO_PRIORIDAD', 'Cambio de prioridad'],
]

export function ResultadoReplanificacion({ r }: { r: ResultadoReplan & { replanificado?: boolean } }) {
  return (
    <div className="panel">
      <h2>Replanificación incremental</h2>
      <p>{r.resumen}</p>
      {r.tandas.map((t) => (
        <p key={t.tanda}>
          RIESGO TANDA {t.tanda}: <Riesgo nivel={t.riesgo_antes} /> → <Riesgo nivel={t.riesgo_despues} /> · fin {f2(t.fin_antes)} → {f2(t.fin_despues)}
          {t.motivos[0] && <span className="pequeno tenue"> · {t.motivos[0]}</span>}
        </p>
      ))}
      {r.cambios.length > 0 ? <TablaCambios cambios={r.cambios} /> : <p className="tenue">El plan no cambia.</p>}
      {r.sale_del_plan.length > 0 && (
        <div className="mensaje error">
          Operaciones que salen del plan:
          <ul>
            {r.sale_del_plan.map((n) => (
              <li key={n.operacion_id}>
                OF {n.of} {n.tipo}: {n.detalle}
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  )
}

export default function Incidencias() {
  const { sesion } = useSesion()
  const lista = useDatos(() => api.get<Inc[]>('/incidencias'), [])
  const recursos = useDatos(() => api.get<{ id: number; codigo: string; nombre: string }[]>('/recursos'), [])
  const operarios = useDatos(() => api.get<{ id: number; codigo: string; nombre: string }[]>('/operarios'), [])
  const [tipo, setTipo] = useState('AVERIA')
  const [recurso, setRecurso] = useState('')
  const [operario, setOperario] = useState('')
  const [ofNum, setOfNum] = useState('')
  const [inicio, setInicio] = useState(isoLocal(new Date()))
  const [horas, setHoras] = useState('4')
  const [minutosExtra, setMinutosExtra] = useState('60')
  const [materialDesde, setMaterialDesde] = useState('')
  const [prioridad, setPrioridad] = useState('')
  const [descripcion, setDescripcion] = useState('')
  const [res, setRes] = useState<ResultadoReplan | null>(null)
  const [err, setErr] = useState<unknown>(null)
  const [enviando, setEnviando] = useState(false)

  const registrar = async () => {
    setErr(null)
    setRes(null)
    setEnviando(true)
    try {
      let of_id: number | null = null
      let operacion_id: number | null = null
      if (ofNum) {
        const r = await api.get<{ items: OFResumen[] }>(`/ofs?q=${encodeURIComponent(ofNum)}`)
        const of = r.items.find((o) => o.numero === ofNum)
        if (!of) throw new Error(`OF ${ofNum} no encontrada`)
        of_id = of.id
        if (tipo === 'RETRASO') {
          const det = await api.get<{ operaciones: { id: number; estado: string }[] }>(`/ofs/${of.id}`)
          operacion_id = det.operaciones.find((o) => o.estado !== 'TERMINADA')?.id ?? null
        }
      }
      const cuerpo = {
        tipo,
        descripcion: descripcion || TIPOS.find((t) => t[0] === tipo)?.[1],
        recurso_id: recurso ? Number(recurso) : null,
        operario_id: operario ? Number(operario) : null,
        of_id,
        operacion_id,
        inicio,
        horas: ['AVERIA', 'AUSENCIA'].includes(tipo) && horas ? Number(horas) : null,
        minutos_extra: tipo === 'RETRASO' ? Number(minutosExtra) : null,
        material_desde: tipo === 'FALTA_MATERIAL' && materialDesde ? materialDesde : null,
        prioridad: tipo === 'CAMBIO_PRIORIDAD' && prioridad ? Number(prioridad) : null,
      }
      setRes(await api.post<ResultadoReplan>('/incidencias', cuerpo))
      lista.recargar()
    } catch (e) {
      setErr(e)
    } finally {
      setEnviando(false)
    }
  }

  return (
    <>
      <div className="cabecera">
        <div>
          <h1>Incidencias</h1>
          <div className="sub">Al registrar una incidencia el sistema recalcula SOLO la zona afectada del plan y muestra qué cambia, por qué y con qué impacto.</div>
        </div>
      </div>
      {puede(sesion, 'incidencias') && (
        <section className="panel">
          <h2>Registrar incidencia</h2>
          <div className="formulario">
            <label className="campo">
              Tipo
              <select value={tipo} onChange={(e) => setTipo(e.target.value)}>
                {TIPOS.map(([k, t]) => (
                  <option key={k} value={k}>
                    {t}
                  </option>
                ))}
              </select>
            </label>
            {tipo === 'AVERIA' && (
              <label className="campo">
                Máquina / recurso
                <select value={recurso} onChange={(e) => setRecurso(e.target.value)}>
                  <option value="">—</option>
                  {(recursos.datos ?? []).map((r) => (
                    <option key={r.id} value={r.id}>
                      {r.codigo} · {r.nombre}
                    </option>
                  ))}
                </select>
              </label>
            )}
            {tipo === 'AUSENCIA' && (
              <label className="campo">
                Trabajador
                <select value={operario} onChange={(e) => setOperario(e.target.value)}>
                  <option value="">—</option>
                  {(operarios.datos ?? []).map((o) => (
                    <option key={o.id} value={o.id}>
                      {o.codigo} · {o.nombre}
                    </option>
                  ))}
                </select>
              </label>
            )}
            {['FALTA_MATERIAL', 'RETRASO', 'CAMBIO_PRIORIDAD'].includes(tipo) && (
              <label className="campo">
                Nº de OF
                <input value={ofNum} onChange={(e) => setOfNum(e.target.value.trim())} placeholder="917251" />
              </label>
            )}
            {['AVERIA', 'AUSENCIA'].includes(tipo) && (
              <>
                <label className="campo">
                  Desde
                  <input type="datetime-local" value={inicio} onChange={(e) => setInicio(e.target.value)} />
                </label>
                <label className="campo">
                  Duración estimada (h, vacío = sin fin conocido)
                  <input type="number" min="0" value={horas} onChange={(e) => setHoras(e.target.value)} />
                </label>
              </>
            )}
            {tipo === 'RETRASO' && (
              <label className="campo">
                Minutos adicionales
                <input type="number" value={minutosExtra} onChange={(e) => setMinutosExtra(e.target.value)} />
              </label>
            )}
            {tipo === 'FALTA_MATERIAL' && (
              <label className="campo">
                Material disponible desde (vacío = sin fecha)
                <input type="datetime-local" value={materialDesde} onChange={(e) => setMaterialDesde(e.target.value)} />
              </label>
            )}
            {tipo === 'CAMBIO_PRIORIDAD' && (
              <label className="campo">
                Nueva prioridad (escala ORTEMS)
                <input type="number" value={prioridad} onChange={(e) => setPrioridad(e.target.value)} />
              </label>
            )}
          </div>
          <label className="campo" style={{ marginTop: 8 }}>
            Descripción
            <textarea value={descripcion} onChange={(e) => setDescripcion(e.target.value)} placeholder="Qué ha pasado" />
          </label>
          <MensajeError error={err} />
          <button className="primario" style={{ marginTop: 8 }} onClick={registrar} disabled={enviando}>
            {enviando ? 'Replanificando…' : 'Registrar y replanificar'}
          </button>
        </section>
      )}
      {res && <ResultadoReplanificacion r={res} />}
      <section className="panel">
        <h2>Registro de incidencias</h2>
        {!lista.datos ? (
          <Cargando />
        ) : (
          <table>
            <thead>
              <tr>
                <th>#</th>
                <th>Tipo</th>
                <th>Descripción</th>
                <th>Afecta a</th>
                <th>Desde</th>
                <th>Impacto</th>
                <th>Estado</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {lista.datos.map((i) => (
                <tr key={i.id}>
                  <td>{i.id}</td>
                  <td className="mono">{i.tipo}</td>
                  <td>
                    {i.descripcion}
                    <div className="pequeno tenue">por {i.reportado_por}</div>
                  </td>
                  <td className="pequeno">{[i.recurso, i.operario, i.of_id && `OF #${i.of_id}`].filter(Boolean).join(' · ')}</td>
                  <td className="pequeno">
                    {fecha(i.inicio)}
                    {i.fin_prevista && ` → ${fecha(i.fin_prevista)}`}
                  </td>
                  <td className="pequeno">{i.impacto?.resumen}</td>
                  <td>
                    <span className="etiqueta">{i.estado}</span>
                  </td>
                  <td>
                    {i.estado === 'ABIERTA' && puede(sesion, 'incidencias') && (
                      <button
                        onClick={async () => {
                          await api.post(`/incidencias/${i.id}/cerrar`)
                          lista.recargar()
                        }}
                      >
                        Cerrar
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>
    </>
  )
}
