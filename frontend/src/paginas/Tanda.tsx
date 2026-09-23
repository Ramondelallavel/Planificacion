import { Link, useParams } from 'react-router-dom'
import { api, puede } from '../api'
import { useSesion } from '../App'
import { Cargando, MensajeError, Riesgo, useDatos } from '../componentes/comunes'
import { fecha, horas, pct, semana } from '../formato'
import type { Nivel } from '../tipos'

interface TandaDet {
  id: number
  numero: string
  producto: string | null
  semana: string | null
  estado: string
  riesgo: Nivel
  motivos: string[] | null
  progreso: number
  carga_restante_h: number | null
  aparatos: {
    id: number
    referencia: string
    numero_control: string
    producto: string | null
    cliente: string | null
    semana: string | null
    riesgo: Nivel
    motivos: string[] | null
    ofs: number
    bultos: number
    carga_restante_h: number | null
    fin_previsto: string | null
    su_referencia: string | null
  }[]
  secciones: { seccion: string | null; ofs: number; horas: number }[]
}

export default function Tanda() {
  const id = Number(useParams().id)
  const { sesion } = useSesion()
  const { datos: t, error, recargar } = useDatos(() => api.get<TandaDet>(`/tandas/${id}`), [id])
  if (error) return <MensajeError error={error} />
  if (!t) return <Cargando />
  return (
    <>
      <div className="cabecera">
        <div>
          <h1>
            TANDA {t.numero} <Riesgo nivel={t.riesgo} texto />
          </h1>
          <div className="sub">
            {t.producto} · semana de fabricación {semana(t.semana)} · progreso {pct(t.progreso)} · {horas(t.carga_restante_h)} pendientes · {t.aparatos.length} aparato(s)
          </div>
        </div>
        {puede(sesion, 'planificar') && (
          <div className="botones">
            <button
              onClick={async () => {
                await api.patch(`/tandas/${id}`, { incluida_en_plan: false, motivo: 'Excluida manualmente del plan' })
                recargar()
              }}
            >
              Excluir del plan
            </button>
            <button
              onClick={async () => {
                await api.patch(`/tandas/${id}`, { incluida_en_plan: true, motivo: 'Incluida en el plan' })
                recargar()
              }}
            >
              Incluir en el plan
            </button>
          </div>
        )}
      </div>
      {t.motivos && t.motivos.length > 0 && (
        <div className="mensaje aviso">
          <ul>
            {t.motivos.map((m, i) => (
              <li key={i}>{m}</li>
            ))}
          </ul>
        </div>
      )}
      <section className="panel">
        <h2>Aparatos / pedidos</h2>
        <table>
          <thead>
            <tr>
              <th>Aparato</th>
              <th>Producto</th>
              <th>Cliente</th>
              <th>Su ref.</th>
              <th>Semana</th>
              <th className="num">OF</th>
              <th className="num">Bultos</th>
              <th className="num">Horas pend.</th>
              <th>Fin previsto</th>
              <th>Riesgo</th>
            </tr>
          </thead>
          <tbody>
            {t.aparatos.map((a) => (
              <tr key={a.id} title={(a.motivos ?? []).join('\n')}>
                <td>
                  <Link to={`/aparatos/${a.id}`}>
                    <strong>{a.referencia}</strong>
                  </Link>
                </td>
                <td>{a.producto ?? <span className="nd">DATO NO DISPONIBLE</span>}</td>
                <td className="pequeno">{a.cliente ?? <span className="nd">—</span>}</td>
                <td className="mono">{a.su_referencia ?? '—'}</td>
                <td>{semana(a.semana)}</td>
                <td className="num">{a.ofs}</td>
                <td className="num">{a.bultos}</td>
                <td className="num">{horas(a.carga_restante_h)}</td>
                <td>{fecha(a.fin_previsto)}</td>
                <td>
                  <Riesgo nivel={a.riesgo} />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>
      <section className="panel">
        <h2>Carga por sección</h2>
        <table>
          <thead>
            <tr>
              <th>Sección</th>
              <th className="num">OF</th>
              <th className="num">Horas estimadas</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {t.secciones.map((s) => (
              <tr key={s.seccion ?? '-'}>
                <td>{s.seccion ?? '—'}</td>
                <td className="num">{s.ofs}</td>
                <td className="num">{horas(s.horas)}</td>
                <td>
                  <Link to={`/ofs?tanda_id=${t.id}&seccion=${s.seccion ?? ''}`}>ver OF</Link>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>
    </>
  )
}
