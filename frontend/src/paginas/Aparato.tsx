import { Link, useParams } from 'react-router-dom'
import { api } from '../api'
import { Cargando, MensajeError, Riesgo, useDatos } from '../componentes/comunes'
import { fecha, horas, semana } from '../formato'
import type { Nivel, OFResumen } from '../tipos'

interface Bulto {
  id: number
  numero: string
  padre_id: number | null
  codigo: string | null
  descripcion: string | null
  largo_mm: number | null
  ancho_mm: number | null
  alto_mm: number | null
  peso_kg: number | null
  estado: string
  fuentes: string[] | null
  of_id: number | null
  componentes: { articulo: string; descripcion: string | null; parametros: string | null; cantidad: number | null; pagina: number | null; traduccion: string | null }[]
}

interface ApDet {
  id: number
  referencia: string
  numero_control: string
  producto: string | null
  cliente: string | null
  su_referencia: string | null
  ffp: string | null
  embalaje: string | null
  semana: string | null
  riesgo: Nivel
  motivos: string[] | null
  tanda_id: number
  fin_previsto: string | null
  carga_restante_h: number | null
  ofs: OFResumen[]
  bultos: Bulto[]
}

function dims(b: Bulto) {
  if (!b.largo_mm) return '—'
  return `${b.largo_mm} × ${b.ancho_mm} × ${b.alto_mm} mm`
}

export default function Aparato() {
  const id = Number(useParams().id)
  const { datos: a, error } = useDatos(() => api.get<ApDet>(`/aparatos/${id}`), [id])
  if (error) return <MensajeError error={error} />
  if (!a) return <Cargando />
  const principales = a.bultos.filter((b) => !b.padre_id)
  const hijos = (pid: number) => a.bultos.filter((b) => b.padre_id === pid)
  return (
    <>
      <div className="cabecera">
        <div>
          <h1>
            APARATO {a.referencia} <Riesgo nivel={a.riesgo} texto />
          </h1>
          <div className="sub">
            {a.producto ?? 'producto DATO NO DISPONIBLE'} · {a.cliente ?? 'cliente DATO NO DISPONIBLE'} · su ref. {a.su_referencia ?? '—'} · FFP {a.ffp ?? '—'} · embalaje{' '}
            {a.embalaje ?? '—'} · {semana(a.semana)} · fin previsto {fecha(a.fin_previsto)} · {horas(a.carga_restante_h)} pendientes ·{' '}
            <Link to={`/tandas/${a.tanda_id}`}>ver tanda</Link>
          </div>
        </div>
      </div>
      {a.motivos && (
        <div className="mensaje aviso">
          <ul>
            {a.motivos.map((m, i) => (
              <li key={i}>{m}</li>
            ))}
          </ul>
        </div>
      )}
      <div className="rejilla dos">
        <section className="panel">
          <h2>Bultos ({principales.length})</h2>
          <p className="pequeno tenue">Composición física reconstruida a partir de la lista de materiales, el packing list y las hojas CAB. Cada bulto indica de qué fuentes procede.</p>
          <div className="arbol">
            {principales.map((b) => (
              <details key={b.id}>
                <summary>
                  <strong>Bulto {b.numero}</strong> · {b.codigo ?? ''} {b.descripcion ?? <span className="nd">sin descripción</span>} · {dims(b)} · {b.peso_kg ?? '—'} kg{' '}
                  {b.of_id && <Link to={`/ofs/${b.of_id}`}>OF</Link>} <span className="tenue pequeno">{(b.fuentes ?? []).join(' · ')}</span>
                </summary>
                <ul>
                  {b.componentes.map((c, i) => (
                    <li key={i} className="pequeno">
                      <span className="mono">{c.articulo}</span> {c.descripcion} {c.parametros && <span className="tenue">({c.parametros})</span>} × {c.cantidad ?? '?'}{' '}
                      <span className="tenue">p.{c.pagina}</span>
                    </li>
                  ))}
                  {hijos(b.id).map((h) => (
                    <li key={h.id}>
                      <details>
                        <summary>
                          <strong>{h.numero}</strong> {h.codigo} {h.descripcion} ({h.componentes.length} componentes)
                        </summary>
                        <ul>
                          {h.componentes.map((c, i) => (
                            <li key={i} className="pequeno">
                              <span className="mono">{c.articulo}</span> {c.descripcion} × {c.cantidad ?? '?'}
                            </li>
                          ))}
                        </ul>
                      </details>
                    </li>
                  ))}
                </ul>
              </details>
            ))}
            {principales.length === 0 && <p className="nd">El documento no contiene lista de bultos para este aparato.</p>}
          </div>
        </section>
        <section className="panel">
          <h2>Órdenes de fabricación ({a.ofs.length})</h2>
          <table>
            <thead>
              <tr>
                <th>OF</th>
                <th>Sección</th>
                <th>Grupo HF</th>
                <th>Estado</th>
                <th>Inicio previsto</th>
                <th>Riesgo</th>
              </tr>
            </thead>
            <tbody>
              {a.ofs.map((o) => (
                <tr key={o.id}>
                  <td>
                    <Link to={`/ofs/${o.id}`}>{o.numero}</Link>
                    {!o.tiene_hoja && <span className="etiqueta" style={{ marginLeft: 4 }}>sin hoja</span>}
                  </td>
                  <td>{o.seccion}</td>
                  <td className="pequeno">{o.grupo_hf}</td>
                  <td className="pequeno">{o.estado}</td>
                  <td className="pequeno">{fecha(o.inicio_previsto)}</td>
                  <td>
                    <Riesgo nivel={o.riesgo} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      </div>
    </>
  )
}
