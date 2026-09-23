import { useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../api'
import { Cargando, MensajeError, Riesgo, useDatos } from '../componentes/comunes'
import { hora } from '../formato'
import type { Asignacion } from '../tipos'

interface Turnos {
  dia: string
  turnos: { turno: string; nombre: string; inicio: string; fin: string; operarios: { operario: string; trabajos: Asignacion[] }[]; sin_operario: Asignacion[] }[]
}

function hoyISO() {
  const d = new Date()
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
}

export default function PlanTurnos() {
  const [dia, setDia] = useState(hoyISO())
  const { datos, error } = useDatos(() => api.get<Turnos>(`/plan/activo/turnos?dia=${dia}`), [dia])
  return (
    <>
      <div className="cabecera">
        <div>
          <h1>Plan por turno</h1>
          <div className="sub">Quién hace qué, en qué máquina y en qué OF, turno a turno.</div>
        </div>
        <input type="date" value={dia} onChange={(e) => setDia(e.target.value)} />
      </div>
      <MensajeError error={error} />
      {!datos ? (
        <Cargando />
      ) : datos.turnos.length === 0 ? (
        <p className="tenue">No hay turnos de trabajo este día.</p>
      ) : (
        <div className="rejilla dos">
          {datos.turnos.map((t) => (
            <section className="panel" key={t.turno}>
              <h2>
                TURNO {t.nombre.toUpperCase()} · {hora(t.inicio)}–{hora(t.fin)}
              </h2>
              {t.operarios.length === 0 && t.sin_operario.length === 0 && <p className="tenue">Sin trabajo planificado.</p>}
              {t.operarios.map((o) => (
                <div key={o.operario} style={{ marginBottom: 10 }}>
                  <strong>{o.operario}</strong>
                  <table>
                    <tbody>
                      {o.trabajos.map((a) => (
                        <tr key={a.operacion_id}>
                          <td className="mono" style={{ width: 95 }}>
                            {hora(a.inicio)}–{hora(a.fin)}
                          </td>
                          <td style={{ width: 110 }}>{a.recurso}</td>
                          <td>
                            <Link to={`/ofs/${a.of_id}`}>OF {a.of}</Link> · {a.tipo} {a.provisional && <span className="etiqueta">provisional</span>}
                            <div className="pequeno tenue">
                              {a.aparato} · tanda {a.tanda}
                            </div>
                          </td>
                          <td style={{ width: 90 }}>
                            <Riesgo nivel={a.riesgo} />
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              ))}
              {t.sin_operario.length > 0 && (
                <>
                  <strong>Sin operario (recursos automáticos)</strong>
                  <ul className="lista-plana">
                    {t.sin_operario.map((a) => (
                      <li key={a.operacion_id}>
                        {hora(a.inicio)}–{hora(a.fin)} · {a.recurso} · OF {a.of}
                      </li>
                    ))}
                  </ul>
                </>
              )}
            </section>
          ))}
        </div>
      )}
    </>
  )
}
