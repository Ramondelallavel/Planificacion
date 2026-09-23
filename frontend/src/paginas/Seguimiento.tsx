import { useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../api'
import { Cargando, Kpi, MensajeError, useDatos } from '../componentes/comunes'
import { fecha, hora, pct } from '../formato'
import { aCsv, descargar } from '../plataforma'

interface DatosSeguimiento {
  ahora: string
  dias: number
  adherencia: { debidas: number; terminadas: number; pct: number | null; pendientes: { of: string; of_id: number; operacion: string; fin_previsto: string; estado: string; recurso: string | null }[] }
  en_curso: { fichaje_id: number; operario: string | null; of: string; of_id: number; operacion: string | null; recurso: string | null; estado: string; inicio: string; trabajado_min: number; previsto_min: number | null; excede: boolean }[]
  resumen: { fichajes: number; previsto_min: number; real_min: number; desviacion_pct: number | null }
  por_tipo: { seccion: string; operacion: string; fichajes: number; previsto_min: number; real_min: number; desviacion_pct: number | null }[]
  mayores_desviaciones: { of: string; of_id: number; operacion: string; seccion: string | null; operario: string | null; fin: string; previsto_min: number; real_min: number; desviacion_min: number }[]
}

const h = (min: number) => `${(min / 60).toLocaleString('es-ES', { maximumFractionDigits: 1 })} h`
const signo = (v: number | null) => (v == null ? '—' : `${v > 0 ? '+' : ''}${v.toLocaleString('es-ES', { maximumFractionDigits: 1 })} %`)
const nivelDesv = (v: number | null) => (v == null ? '' : Math.abs(v) >= 25 ? 'ROJO' : Math.abs(v) >= 10 ? 'AMARILLO' : 'VERDE')

/** Plan frente a real: adherencia, trabajo en curso y desviaciones de tiempos. */
export default function Seguimiento() {
  const [dias, setDias] = useState(14)
  const { datos, error, recargar } = useDatos(() => api.get<DatosSeguimiento>(`/dashboard/seguimiento?dias=${dias}`), [dias], 60000)
  if (error) return <MensajeError error={error} />
  if (!datos) return <Cargando />
  const { adherencia, resumen } = datos
  return (
    <>
      <div className="cabecera">
        <div>
          <h1>Seguimiento</h1>
          <div className="sub">Lo que dice el plan frente a lo que pasa en planta, con los fichajes de los operarios. Las desviaciones alimentan el aprendizaje de tiempos.</div>
        </div>
        <div className="botones">
          <select id="seg-dias" value={dias} onChange={(e) => setDias(Number(e.target.value))}>
            <option value={7}>Últimos 7 días</option>
            <option value={14}>Últimos 14 días</option>
            <option value={30}>Últimos 30 días</option>
          </select>
          <button onClick={recargar}>Actualizar</button>
        </div>
      </div>

      <div className="kpis">
        <Kpi
          valor={adherencia.pct == null ? '—' : pct(adherencia.pct)}
          etiqueta={`Adherencia al plan (${adherencia.terminadas} de ${adherencia.debidas} operaciones que ya debían estar)`}
          nivel={adherencia.pct == null ? undefined : adherencia.pct >= 0.9 ? 'VERDE' : adherencia.pct >= 0.7 ? 'AMARILLO' : 'ROJO'}
        />
        <Kpi valor={datos.en_curso.length} etiqueta={`Trabajos en curso${datos.en_curso.some((e) => e.excede) ? ` · ${datos.en_curso.filter((e) => e.excede).length} fuera de tiempo` : ''}`} nivel={datos.en_curso.some((e) => e.excede) ? 'NARANJA' : undefined} />
        <Kpi valor={resumen.fichajes} etiqueta={`Operaciones terminadas en ${datos.dias} días`} />
        <Kpi valor={signo(resumen.desviacion_pct)} etiqueta={`Tiempo real frente a previsto (${h(resumen.real_min)} / ${h(resumen.previsto_min)})`} nivel={nivelDesv(resumen.desviacion_pct) || undefined} />
      </div>

      <div className="rejilla dos">
        <section className="panel">
          <h2>En curso ahora</h2>
          {datos.en_curso.length === 0 ? (
            <p className="tenue">Nadie tiene un trabajo abierto.</p>
          ) : (
            <table>
              <thead>
                <tr>
                  <th>Operario</th>
                  <th>OF · operación</th>
                  <th className="num">Llevado / previsto</th>
                </tr>
              </thead>
              <tbody>
                {datos.en_curso.map((e) => (
                  <tr key={e.fichaje_id}>
                    <td>
                      {e.operario}
                      <div className="pequeno tenue">
                        {e.recurso} · desde {hora(e.inicio)} {e.estado === 'PAUSADO' && <span className="etiqueta">en pausa</span>}
                      </div>
                    </td>
                    <td>
                      <Link to={`/ofs/${e.of_id}`}>OF {e.of}</Link> · {e.operacion}
                    </td>
                    <td className="num">
                      <span className={e.excede ? 'riesgo NARANJA' : ''}>
                        {e.trabajado_min} / {e.previsto_min != null ? Math.round(e.previsto_min) : '—'} min
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </section>
        <section className="panel">
          <h2>Debían estar terminadas y no lo están</h2>
          {adherencia.pendientes.length === 0 ? (
            <p className="tenue">{adherencia.debidas ? 'Todo lo previsto hasta ahora está terminado.' : 'El plan aún no preveía terminar nada.'}</p>
          ) : (
            <table>
              <tbody>
                {adherencia.pendientes.map((p, i) => (
                  <tr key={i}>
                    <td>
                      <Link to={`/ofs/${p.of_id}`}>OF {p.of}</Link> · {p.operacion}
                    </td>
                    <td className="pequeno">{p.recurso}</td>
                    <td className="pequeno">fin previsto {fecha(p.fin_previsto)}</td>
                    <td>
                      <span className="etiqueta">{p.estado}</span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </section>
      </div>

      <section className="panel">
        <div className="cabecera">
          <h2>Desviación por sección y operación</h2>
          <button
            disabled={!datos.por_tipo.length}
            onClick={() =>
              descargar(
                'desviaciones.csv',
                aCsv(datos.por_tipo as unknown as Record<string, unknown>[], [
                  ['seccion', 'Sección'],
                  ['operacion', 'Operación'],
                  ['fichajes', 'Operaciones'],
                  ['previsto_min', 'Minutos previstos'],
                  ['real_min', 'Minutos reales'],
                  ['desviacion_pct', 'Desviación %'],
                ]),
                'text/csv',
              )
            }
          >
            Exportar CSV
          </button>
        </div>
        {datos.por_tipo.length === 0 ? (
          <p className="tenue">Aún no hay operaciones terminadas con fichaje en este periodo.</p>
        ) : (
          <table>
            <thead>
              <tr>
                <th>Sección</th>
                <th>Operación</th>
                <th className="num">Operaciones</th>
                <th className="num">Previsto</th>
                <th className="num">Real</th>
                <th className="num">Desviación</th>
              </tr>
            </thead>
            <tbody>
              {datos.por_tipo.map((t) => (
                <tr key={`${t.seccion}-${t.operacion}`}>
                  <td>{t.seccion}</td>
                  <td>{t.operacion}</td>
                  <td className="num">{t.fichajes}</td>
                  <td className="num">{h(t.previsto_min)}</td>
                  <td className="num">{h(t.real_min)}</td>
                  <td className="num">
                    <span className={`riesgo ${nivelDesv(t.desviacion_pct)}`}>{signo(t.desviacion_pct)}</span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
        <p className="pequeno tenue">
          Si una operación se desvía de forma sistemática, <Link to="/configuracion">Configuración → Aprendizaje de tiempos</Link> propone ajustar su tiempo estándar (nunca se aplica sin
          aprobación).
        </p>
      </section>

      {datos.mayores_desviaciones.length > 0 && (
        <section className="panel">
          <h2>Mayores desviaciones</h2>
          <table>
            <thead>
              <tr>
                <th>OF · operación</th>
                <th>Operario</th>
                <th>Terminada</th>
                <th className="num">Previsto</th>
                <th className="num">Real</th>
                <th className="num">Diferencia</th>
              </tr>
            </thead>
            <tbody>
              {datos.mayores_desviaciones.map((d, i) => (
                <tr key={i}>
                  <td>
                    <Link to={`/ofs/${d.of_id}`}>OF {d.of}</Link> · {d.operacion} <span className="pequeno tenue">{d.seccion}</span>
                  </td>
                  <td>{d.operario}</td>
                  <td className="pequeno">{fecha(d.fin)}</td>
                  <td className="num">{d.previsto_min} min</td>
                  <td className="num">{d.real_min} min</td>
                  <td className="num">
                    {d.desviacion_min > 0 ? '+' : ''}
                    {d.desviacion_min} min
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      )}
    </>
  )
}
