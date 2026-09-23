import { Fragment, useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../api'
import { Cargando, MensajeError, useDatos } from '../componentes/comunes'
import { hora } from '../formato'
import type { Asignacion } from '../tipos'

interface Celda {
  disponible: number
  ocupado: number
}
interface DatosCapacidad {
  plan_id: number | null
  ahora: string
  dias: string[]
  recursos: { id: number; codigo: string; nombre: string; seccion: string | null; estado: string; celdas: Celda[] }[]
  secciones: { seccion: string; celdas: Celda[] }[]
}

const DIAS = ['dom', 'lun', 'mar', 'mié', 'jue', 'vie', 'sáb']
const cabecera = (iso: string) => {
  const d = new Date(iso + 'T12:00:00')
  return { dia: DIAS[d.getDay()], num: `${d.getDate()}/${d.getMonth() + 1}`, finde: d.getDay() === 0 || d.getDay() === 6 }
}
const nivel = (c: Celda) => {
  if (!c.disponible) return c.ocupado ? 'critico' : 'cerrado'
  const u = c.ocupado / c.disponible
  return u >= 0.95 ? 'critico' : u >= 0.8 ? 'alto' : u >= 0.5 ? 'medio' : u > 0 ? 'bajo' : 'libre'
}
const texto = (c: Celda) => (!c.disponible ? (c.ocupado ? '!' : '—') : `${Math.round((100 * c.ocupado) / c.disponible)}%`)
const titulo = (c: Celda) =>
  !c.disponible ? 'Sin turno ese día' : `${(c.ocupado / 60).toLocaleString('es-ES', { maximumFractionDigits: 1 })} h planificadas de ${(c.disponible / 60).toLocaleString('es-ES', { maximumFractionDigits: 1 })} h disponibles`

/** Ocupación planificada frente a capacidad real, por máquina y día. */
export default function Capacidad() {
  const [dias, setDias] = useState(14)
  const { datos, error, recargar } = useDatos(() => api.get<DatosCapacidad>(`/plan/activo/capacidad?dias=${dias}`), [dias])
  const [celda, setCelda] = useState<{ recurso: DatosCapacidad['recursos'][number]; dia: string } | null>(null)
  const detalle = useDatos(
    () =>
      celda
        ? api.get<{ asignaciones: Asignacion[] }>(`/plan/activo/gantt?recurso_id=${celda.recurso.id}&desde=${celda.dia}T00:00:00&hasta=${celda.dia}T23:59:59`)
        : Promise.resolve(null),
    [celda],
  )
  if (error) return <MensajeError error={error} />
  if (!datos) return <Cargando />

  // máquinas más cargadas en los próximos 5 días con turno
  const conTurno = datos.dias.map((_, i) => datos.recursos.some((r) => r.celdas[i].disponible > 0))
  const proximos = conTurno.map((v, i) => (v ? i : -1)).filter((i) => i >= 0).slice(0, 5)
  const ranking = datos.recursos
    .map((r) => {
      const disp = proximos.reduce((n, i) => n + r.celdas[i].disponible, 0)
      const oc = proximos.reduce((n, i) => n + r.celdas[i].ocupado, 0)
      return { r, u: disp ? oc / disp : 0, horas: oc / 60 }
    })
    .filter((x) => x.horas > 0)
    .sort((a, b) => b.u - a.u)
    .slice(0, 5)

  return (
    <>
      <div className="cabecera">
        <div>
          <h1>Capacidad</h1>
          <div className="sub">
            Ocupación del plan frente a la capacidad real de cada máquina: turnos, jornadas extra, festivos y paradas. Un día al 95 % o más es un cuello de botella; uno bajo es hueco para
            adelantar trabajo.
          </div>
        </div>
        <div className="botones">
          <select id="cap-dias" value={dias} onChange={(e) => setDias(Number(e.target.value))}>
            <option value={7}>7 días</option>
            <option value={14}>14 días</option>
            <option value={21}>21 días</option>
          </select>
          <button onClick={recargar}>Actualizar</button>
        </div>
      </div>
      {!datos.plan_id && <div className="mensaje aviso">No hay plan activo: se muestra solo la capacidad disponible.</div>}

      {ranking.length > 0 && (
        <section className="panel">
          <h2>Más cargadas en los próximos {proximos.length} días laborables</h2>
          <div className="ranking-capacidad">
            {ranking.map(({ r, u, horas }) => (
              <div key={r.id} className={`tarjeta-cap ${u >= 0.95 ? 'critico' : u >= 0.8 ? 'alto' : ''}`}>
                <div className="valor">{Math.round(u * 100)}%</div>
                <div>
                  <strong>{r.codigo}</strong> <span className="pequeno tenue">{r.seccion}</span>
                </div>
                <div className="pequeno tenue">{horas.toLocaleString('es-ES', { maximumFractionDigits: 1 })} h planificadas</div>
              </div>
            ))}
          </div>
        </section>
      )}

      <section className="panel">
        <div className="leyenda-cap pequeno">
          <span className="celda-cap libre">0%</span> libre <span className="celda-cap bajo">1–49%</span> <span className="celda-cap medio">50–79%</span>{' '}
          <span className="celda-cap alto">80–94%</span> <span className="celda-cap critico">≥95%</span> cuello de botella <span className="celda-cap cerrado">—</span> sin turno
        </div>
        <div className="tabla-desplazable">
          <table className="mapa-cap">
            <thead>
              <tr>
                <th>Máquina / sección</th>
                {datos.dias.map((d) => {
                  const c = cabecera(d)
                  return (
                    <th key={d} className={`num ${c.finde ? 'finde' : ''}`}>
                      <div>{c.dia}</div>
                      <div className="pequeno tenue">{c.num}</div>
                    </th>
                  )
                })}
              </tr>
            </thead>
            <tbody>
              {datos.secciones.map((sec) => (
                <Fragment key={sec.seccion}>
                  <tr className="fila-seccion">
                    <td>
                      <strong>{sec.seccion}</strong>
                    </td>
                    {sec.celdas.map((c, i) => (
                      <td key={i} className={`celda-cap ${nivel(c)}`} title={titulo(c)}>
                        {texto(c)}
                      </td>
                    ))}
                  </tr>
                  {datos.recursos
                    .filter((r) => (r.seccion ?? '—') === sec.seccion)
                    .map((r) => (
                      <tr key={r.id}>
                        <td className="pequeno">
                          {r.codigo} {r.estado !== 'OPERATIVO' && <span className="riesgo ROJO">{r.estado}</span>}
                        </td>
                        {r.celdas.map((c, i) => (
                          <td
                            key={i}
                            className={`celda-cap ${nivel(c)} ${celda?.recurso.id === r.id && celda.dia === datos.dias[i] ? 'elegida' : ''}`}
                            title={titulo(c)}
                            onClick={() => c.ocupado && setCelda({ recurso: r, dia: datos.dias[i] })}
                            style={{ cursor: c.ocupado ? 'pointer' : 'default' }}
                          >
                            {texto(c)}
                          </td>
                        ))}
                      </tr>
                    ))}
                </Fragment>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      {celda && (
        <section className="panel">
          <div className="cabecera">
            <h2>
              {celda.recurso.codigo} · {cabecera(celda.dia).dia} {cabecera(celda.dia).num}
            </h2>
            <button onClick={() => setCelda(null)}>Cerrar</button>
          </div>
          {!detalle.datos ? (
            <Cargando />
          ) : (
            <table>
              <tbody>
                {detalle.datos.asignaciones.map((a) => (
                  <tr key={a.operacion_id}>
                    <td className="mono">
                      {hora(a.inicio)}–{hora(a.fin)}
                    </td>
                    <td>
                      <Link to={`/ofs/${a.of_id}`}>OF {a.of}</Link> · {a.tipo}
                    </td>
                    <td className="pequeno">{a.operario ?? '—'}</td>
                    <td className="pequeno tenue">
                      {a.aparato} · tanda {a.tanda}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </section>
      )}
    </>
  )
}
