import { useState } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import { api, puede } from '../api'
import { useSesion } from '../App'
import { NuevaOF } from '../componentes/EditorOperaciones'
import { Cargando, MensajeError, Riesgo, useDatos } from '../componentes/comunes'
import { fecha, horas, semana } from '../formato'
import type { OFResumen } from '../tipos'
import { aCsv, descargar } from '../plataforma'

export default function TablaOFs() {
  const [params, setParams] = useSearchParams()
  const [q, setQ] = useState(params.get('q') ?? '')
  const [nueva, setNueva] = useState(false)
  const { sesion } = useSesion()
  const navegar = useNavigate()
  const consulta = params.toString()
  const { datos, error } = useDatos(() => api.get<{ total: number; items: OFResumen[] }>(`/ofs?limite=500&${consulta}`), [consulta])
  const filtro = (k: string, v: string) => {
    const p = new URLSearchParams(params)
    if (v) p.set(k, v)
    else p.delete(k)
    setParams(p)
  }
  return (
    <>
      <div className="cabecera">
        <div>
          <h1>Órdenes de fabricación</h1>
          <div className="sub">{datos ? `${datos.total} OF` : ''}</div>
        </div>
        <div className="botones">
          <form
            onSubmit={(e) => {
              e.preventDefault()
              filtro('q', q)
            }}
          >
            <input placeholder="Buscar OF, grupo, título…" value={q} onChange={(e) => setQ(e.target.value)} />
          </form>
          <select value={params.get('riesgo') ?? ''} onChange={(e) => filtro('riesgo', e.target.value)}>
            <option value="">Todo riesgo</option>
            <option>ROJO</option>
            <option>NARANJA</option>
            <option>AMARILLO</option>
            <option>VERDE</option>
          </select>
          <select value={params.get('estado') ?? ''} onChange={(e) => filtro('estado', e.target.value)}>
            <option value="">Todo estado</option>
            {['NO_INICIADA', 'PLANIFICADA', 'EN_CURSO', 'PAUSADA', 'TERMINADA', 'ESPERANDO_PROGRAMACION', 'ESPERANDO_MATERIAL', 'BLOQUEADA'].map((e) => (
              <option key={e}>{e}</option>
            ))}
          </select>
          <input placeholder="Sección" style={{ width: 90 }} value={params.get('seccion') ?? ''} onChange={(e) => filtro('seccion', e.target.value.toUpperCase())} />
          <button
            disabled={!datos?.items.length}
            onClick={() =>
              datos &&
              descargar(
                'ordenes-fabricacion.csv',
                aCsv(datos.items as unknown as Record<string, unknown>[], [
                  ['numero', 'OF'],
                  ['seccion', 'Sección'],
                  ['grupo_hf', 'Grupo HF'],
                  ['descripcion', 'Descripción'],
                  ['semana', 'Semana'],
                  ['estado', 'Estado'],
                  ['estado_programacion', 'Programación'],
                  ['programa', 'Programa'],
                  ['horas_estimadas', 'Horas estimadas'],
                  ['riesgo', 'Riesgo'],
                  ['inicio_previsto', 'Inicio previsto'],
                  ['fin_previsto', 'Fin previsto'],
                ]),
                'text/csv',
              )
            }
          >
            Exportar CSV
          </button>
          {puede(sesion, 'modificar_plan') && (
            <button className="primario" onClick={() => setNueva(true)}>
              + Nueva OF
            </button>
          )}
        </div>
      </div>
      {nueva && <NuevaOF onCerrar={() => setNueva(false)} onHecho={(of) => navegar(`/ofs/${of.id}`)} />}
      <MensajeError error={error} />
      {!datos ? (
        <Cargando />
      ) : (
        <section className="panel">
          <table>
            <thead>
              <tr>
                <th>OF</th>
                <th>Sección</th>
                <th>Grupo HF</th>
                <th>Título</th>
                <th>Semana</th>
                <th>Estado</th>
                <th>Programación</th>
                <th className="num">Horas est.</th>
                <th>Inicio previsto</th>
                <th>Fin previsto</th>
                <th>Riesgo</th>
              </tr>
            </thead>
            <tbody>
              {datos.items.map((o) => (
                <tr key={o.id}>
                  <td>
                    <Link to={`/ofs/${o.id}`}>
                      <strong>{o.numero}</strong>
                    </Link>
                    {o.urgente && <span className="etiqueta" style={{ marginLeft: 4, color: 'var(--rojo)' }}>URGENTE</span>}
                    {!o.tiene_hoja && <span className="etiqueta" style={{ marginLeft: 4 }}>sin hoja</span>}
                  </td>
                  <td>{o.seccion}</td>
                  <td className="pequeno">{o.grupo_hf}</td>
                  <td className="pequeno">{o.descripcion}</td>
                  <td className="pequeno">{semana(o.semana)}</td>
                  <td className="pequeno">{o.estado}</td>
                  <td className="pequeno">{o.estado_programacion === 'NO_REQUIERE' ? '—' : o.estado_programacion}</td>
                  <td className="num">{o.horas_estimadas === null ? <span className="nd">N/D</span> : horas(o.horas_estimadas)}</td>
                  <td className="pequeno">{fecha(o.inicio_previsto)}</td>
                  <td className="pequeno">{fecha(o.fin_previsto)}</td>
                  <td>
                    <Riesgo nivel={o.riesgo} />
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
