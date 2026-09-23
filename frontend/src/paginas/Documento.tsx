import { useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { api, imagenConToken, puede, urlImagenPagina } from '../api'
import { useSesion } from '../App'
import { Cargando, MensajeError, Modal, Riesgo, useDatos } from '../componentes/comunes'
import { fecha } from '../formato'
import { Progreso, type Trabajo } from './Importacion'

interface DocDetalle {
  id: number
  nombre: string
  hash: string
  tamano_bytes: number
  paginas: number | null
  fecha_carga: string
  usuario: string
  estado: string
  clave: string | null
  version: number
  resumen: Record<string, unknown> | null
  trabajos: Trabajo[]
  versiones: { id: number; version: number; estado: string; fecha_carga: string; nombre: string }[]
  tipos_pagina: Record<string, number>
}

interface Incidencia {
  id: number
  pagina: number | null
  tipo: string
  severidad: string
  mensaje: string
  entidad_tipo: string | null
  entidad_ref: string | null
  texto_origen: string | null
  alternativas: unknown[] | null
  estado: string
  resuelta_por: string | null
  resolucion: string | null
}

const SEV_NIVEL: Record<string, string> = { CRITICA: 'ROJO', ERROR: 'NARANJA', ADVERTENCIA: 'AMARILLO', INFO: 'VERDE' }

export function VisorPagina({ docId, pagina, onCerrar }: { docId: number; pagina: number; onCerrar: () => void }) {
  const [url, setUrl] = useState<string | null>(null)
  const { datos } = useDatos(() => api.get<{ texto: string; tipo: string; bloque: number; metodo: string }>(`/documentos/${docId}/paginas/${pagina}`), [docId, pagina])
  useEffect(() => {
    let u: string | null = null
    imagenConToken(urlImagenPagina(docId, pagina)).then((x) => {
      u = x
      setUrl(x)
    })
    return () => {
      if (u) URL.revokeObjectURL(u)
    }
  }, [docId, pagina])
  return (
    <Modal titulo={`Documento #${docId} · página ${pagina}`} onCerrar={onCerrar}>
      {datos && (
        <p className="pequeno tenue">
          Tipo {datos.tipo} · bloque {datos.bloque} · extracción {datos.metodo}
        </p>
      )}
      <div className="rejilla dos">
        <div>{url ? <img src={url} alt={`Página ${pagina}`} style={{ width: '100%', border: '1px solid var(--borde)' }} /> : <Cargando />}</div>
        <pre className="mono" style={{ whiteSpace: 'pre-wrap', maxHeight: 700, overflow: 'auto', background: 'var(--panel-2)', padding: 10, borderRadius: 6 }}>
          {datos?.texto || '(sin texto extraíble)'}
        </pre>
      </div>
    </Modal>
  )
}

export default function Documento() {
  const id = Number(useParams().id)
  const { sesion } = useSesion()
  const { datos: d, error, recargar } = useDatos(() => api.get<DocDetalle>(`/documentos/${id}`), [id])
  const [sev, setSev] = useState('')
  const [estado, setEstado] = useState('ABIERTA')
  const inc = useDatos(() => api.get<Incidencia[]>(`/documentos/${id}/incidencias?${sev ? `severidad=${sev}&` : ''}${estado ? `estado=${estado}` : ''}`), [id, sev, estado])
  const [pagina, setPagina] = useState<number | null>(null)
  const [revisar, setRevisar] = useState<Incidencia | null>(null)
  if (error) return <MensajeError error={error} />
  if (!d) return <Cargando />
  const r = (d.resumen ?? {}) as Record<string, number>
  const procesando = d.trabajos.find((t) => ['EN_COLA', 'PROCESANDO'].includes(t.estado))
  return (
    <>
      <div className="cabecera">
        <div>
          <h1>{d.nombre}</h1>
          <div className="sub">
            {d.clave ?? 'sin clave lógica'} · versión {d.version} · {d.paginas} páginas · {(d.tamano_bytes / 1e6).toFixed(1)} MB · cargado {fecha(d.fecha_carga)} por {d.usuario} ·{' '}
            <span className="mono pequeno">sha256 {d.hash.slice(0, 16)}…</span>
          </div>
        </div>
        <span className="etiqueta">{d.estado}</span>
      </div>
      {procesando && <Progreso trabajoId={procesando.id} onFin={recargar} />}
      {d.resumen && (
        <div className="rejilla dos">
          <section className="panel">
            <h2>DOCUMENTO PROCESADO</h2>
            <table>
              <tbody>
                <tr><td>Páginas</td><td className="num">{r.paginas}</td></tr>
                <tr><td>OF detectadas (con hoja)</td><td className="num">{r.ofs}</td></tr>
                <tr><td>OF referenciadas sin hoja</td><td className="num">{r.ofs_referenciadas_sin_hoja}</td></tr>
                <tr><td>Aparatos detectados</td><td className="num">{r.aparatos}</td></tr>
                <tr><td>Bultos detectados</td><td className="num">{r.bultos}</td></tr>
                <tr><td>Secciones detectadas</td><td className="num">{r.secciones}</td></tr>
                <tr><td>Líneas (piezas/componentes)</td><td className="num">{r.lineas}</td></tr>
                <tr><td>Dependencias entre OF</td><td className="num">{r.dependencias}</td></tr>
                <tr><td>Errores críticos</td><td className="num"><strong>{r.criticas}</strong></td></tr>
                <tr><td>Errores</td><td className="num">{r.errores}</td></tr>
                <tr><td>Advertencias</td><td className="num">{r.advertencias}</td></tr>
                <tr><td>Datos sin identificar</td><td className="num">{r.datos_sin_identificar}</td></tr>
                <tr><td>Relaciones incompletas</td><td className="num">{r.relaciones_incompletas}</td></tr>
                <tr><td>Operaciones sin tiempo estándar</td><td className="num">{r.operaciones_sin_tiempo}</td></tr>
              </tbody>
            </table>
            {r.criticas > 0 && <div className="mensaje error">Hay errores críticos de integridad: no se permite generar un plan definitivo hasta revisarlos.</div>}
          </section>
          <section className="panel">
            <h2>Páginas por tipo</h2>
            <table>
              <tbody>
                {Object.entries(d.tipos_pagina).map(([k, v]) => (
                  <tr key={k}>
                    <td>{k}</td>
                    <td className="num">{v}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            <p className="pequeno tenue">{String(d.resumen.plan_bloques ?? '')}</p>
            {d.versiones.length > 1 && (
              <>
                <h3>Versiones de {d.clave}</h3>
                <ul className="lista-plana">
                  {d.versiones.map((v) => (
                    <li key={v.id}>
                      <Link to={`/documentos/${v.id}`}>v{v.version}</Link> · {v.nombre} · {fecha(v.fecha_carga)} · <span className="etiqueta">{v.estado}</span>
                    </li>
                  ))}
                </ul>
              </>
            )}
            {d.resumen.tanda ? <p>Tanda: <Link to="/tandas">{String(d.resumen.tanda)}</Link></p> : null}
          </section>
        </div>
      )}
      <section className="panel" style={{ marginTop: 14 }}>
        <div className="cabecera" style={{ marginBottom: 8 }}>
          <h2>Incidencias de datos (REVISIÓN NECESARIA)</h2>
          <div className="botones">
            <select value={sev} onChange={(e) => setSev(e.target.value)}>
              <option value="">Todas las severidades</option>
              <option>CRITICA</option>
              <option>ERROR</option>
              <option>ADVERTENCIA</option>
              <option>INFO</option>
            </select>
            <select value={estado} onChange={(e) => setEstado(e.target.value)}>
              <option value="">Todos los estados</option>
              <option>ABIERTA</option>
              <option>REVISADA</option>
              <option>RESUELTA</option>
              <option>IGNORADA</option>
            </select>
          </div>
        </div>
        {!inc.datos ? (
          <Cargando />
        ) : inc.datos.length === 0 ? (
          <p className="tenue">Sin incidencias con este filtro.</p>
        ) : (
          <table>
            <thead>
              <tr>
                <th>Severidad</th>
                <th>Tipo</th>
                <th>Pág.</th>
                <th>Entidad</th>
                <th>Mensaje</th>
                <th>Estado</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {inc.datos.map((i) => (
                <tr key={i.id}>
                  <td>
                    <Riesgo nivel={SEV_NIVEL[i.severidad]} /> <span className="pequeno">{i.severidad}</span>
                  </td>
                  <td className="mono">{i.tipo}</td>
                  <td>{i.pagina ? <a onClick={() => setPagina(i.pagina)} style={{ cursor: 'pointer' }}>{i.pagina}</a> : '—'}</td>
                  <td className="pequeno">
                    {i.entidad_tipo} {i.entidad_ref}
                  </td>
                  <td>
                    {i.mensaje}
                    {i.texto_origen && <div className="mono tenue pequeno">«{i.texto_origen.slice(0, 180)}»</div>}
                    {i.alternativas && i.alternativas.length > 0 && <div className="pequeno">Alternativas: {JSON.stringify(i.alternativas).slice(0, 200)}</div>}
                    {i.resolucion && <div className="pequeno">Resolución ({i.resuelta_por}): {i.resolucion}</div>}
                  </td>
                  <td>
                    <span className="etiqueta">{i.estado}</span>
                  </td>
                  <td>{puede(sesion, 'validar_datos') && <button onClick={() => setRevisar(i)}>Revisar</button>}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>
      {pagina && <VisorPagina docId={id} pagina={pagina} onCerrar={() => setPagina(null)} />}
      {revisar && (
        <RevisarIncidencia
          inc={revisar}
          onCerrar={() => setRevisar(null)}
          onHecho={() => {
            setRevisar(null)
            inc.recargar()
          }}
        />
      )}
    </>
  )
}

function RevisarIncidencia({ inc, onCerrar, onHecho }: { inc: Incidencia; onCerrar: () => void; onHecho: () => void }) {
  const [estado, setEstado] = useState('REVISADA')
  const [resolucion, setResolucion] = useState('')
  const [err, setErr] = useState<unknown>(null)
  return (
    <Modal titulo={`Revisar incidencia ${inc.tipo}`} onCerrar={onCerrar}>
      <p>{inc.mensaje}</p>
      <div className="formulario">
        <label className="campo">
          Nuevo estado
          <select value={estado} onChange={(e) => setEstado(e.target.value)}>
            <option>REVISADA</option>
            <option>RESUELTA</option>
            <option>IGNORADA</option>
            <option>ABIERTA</option>
          </select>
        </label>
      </div>
      <label className="campo" style={{ marginTop: 10 }}>
        Resolución / motivo (obligatorio para RESUELTA o IGNORADA)
        <textarea value={resolucion} onChange={(e) => setResolucion(e.target.value)} />
      </label>
      <MensajeError error={err} />
      <div className="botones" style={{ marginTop: 10 }}>
        <button
          className="primario"
          onClick={async () => {
            try {
              await api.patch(`/incidencias-datos/${inc.id}`, { estado, resolucion: resolucion || null })
              onHecho()
            } catch (e) {
              setErr(e)
            }
          }}
        >
          Guardar
        </button>
      </div>
    </Modal>
  )
}
