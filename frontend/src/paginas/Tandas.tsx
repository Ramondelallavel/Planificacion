import { Link } from 'react-router-dom'
import { api } from '../api'
import { Cargando, MensajeError, Riesgo, useDatos } from '../componentes/comunes'
import { horas, pct, semana } from '../formato'
import type { Nivel } from '../tipos'

interface TandaFila {
  id: number
  numero: string
  producto: string | null
  semana: string | null
  estado: string
  riesgo: Nivel
  motivos: string[] | null
  progreso: number
  carga_restante_h: number | null
  aparatos: number
  ofs: number
  ofs_terminadas: number
  incluida_en_plan: boolean
}

export default function Tandas() {
  const { datos, error } = useDatos(() => api.get<TandaFila[]>('/tandas'), [])
  if (error) return <MensajeError error={error} />
  if (!datos) return <Cargando />
  return (
    <>
      <div className="cabecera">
        <div>
          <h1>Tandas</h1>
          <div className="sub">Una tanda no tiene un número fijo de aparatos: se muestran los que contiene realmente cada documento.</div>
        </div>
      </div>
      <section className="panel">
        {datos.length === 0 ? (
          <p className="tenue">
            No hay tandas. <Link to="/importacion">Importa el PDF de una tanda</Link>.
          </p>
        ) : (
          <table>
            <thead>
              <tr>
                <th>Tanda</th>
                <th>Producto</th>
                <th>Semana</th>
                <th className="num">Aparatos</th>
                <th className="num">OF</th>
                <th className="num">Progreso</th>
                <th className="num">Horas pendientes</th>
                <th>Riesgo</th>
                <th>Motivo principal</th>
              </tr>
            </thead>
            <tbody>
              {datos.map((t) => (
                <tr key={t.id}>
                  <td>
                    <Link to={`/tandas/${t.id}`}>
                      <strong>{t.numero}</strong>
                    </Link>
                    {!t.incluida_en_plan && <span className="etiqueta" style={{ marginLeft: 6 }}>fuera del plan</span>}
                  </td>
                  <td>{t.producto}</td>
                  <td>{semana(t.semana)}</td>
                  <td className="num">{t.aparatos}</td>
                  <td className="num">
                    {t.ofs_terminadas}/{t.ofs}
                  </td>
                  <td className="num">{pct(t.progreso)}</td>
                  <td className="num">{horas(t.carga_restante_h)}</td>
                  <td>
                    <Riesgo nivel={t.riesgo} />
                  </td>
                  <td className="pequeno">{t.motivos?.[0] ?? ''}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>
    </>
  )
}
