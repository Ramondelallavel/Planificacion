import { useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../api'
import { Cargando, MensajeError, useDatos } from '../componentes/comunes'
import { fecha } from '../formato'

interface Doc {
  id: number
  nombre: string
  paginas: number | null
  fecha_carga: string
  usuario: string
  estado: string
  clave: string | null
  version: number
  resumen: Record<string, number> | null
}

export interface Trabajo {
  id: number
  documento_id: number
  estado: string
  fase: string | null
  paginas_procesadas: number
  paginas_totales: number
  porcentaje: number
  bloque_actual: number
  bloques_totales: number
  tamano_bloque: number
  eta_segundos: number | null
  contadores: Record<string, number | string>
  error: string | null
}

interface Carga {
  documento_id: number
  trabajo_id: number | null
  duplicado: boolean
  nueva_version: boolean
  version: number
  mensaje: string
}

export function Progreso({ trabajoId, onFin }: { trabajoId: number; onFin?: () => void }) {
  const [t, setT] = useState<Trabajo | null>(null)
  const avisado = useRef(false)
  useEffect(() => {
    let vivo = true
    const tick = async () => {
      try {
        const x = await api.get<Trabajo>(`/trabajos/${trabajoId}`)
        if (!vivo) return
        setT(x)
        if (['COMPLETADO', 'ERROR', 'CANCELADO'].includes(x.estado)) {
          if (!avisado.current) {
            avisado.current = true
            onFin?.()
          }
          return
        }
      } catch {
        /* se reintenta */
      }
      if (vivo) window.setTimeout(tick, 1000)
    }
    tick()
    return () => {
      vivo = false
    }
  }, [trabajoId, onFin])
  if (!t) return <Cargando />
  const c = t.contadores
  return (
    <div className="panel">
      <h2>
        {t.estado === 'COMPLETADO' ? 'PROCESADO' : t.estado === 'ERROR' ? 'ERROR EN EL PROCESAMIENTO' : 'PROCESANDO'} documento #{t.documento_id}
      </h2>
      <div className="progreso">
        <div style={{ width: `${t.porcentaje}%` }} />
      </div>
      <p className="mono" style={{ margin: '8px 0' }}>
        {t.porcentaje}% · {t.paginas_procesadas} / {t.paginas_totales} páginas · bloque {t.bloque_actual}
        {t.bloques_totales ? ` de ~${t.bloques_totales}` : ''} ({t.tamano_bloque || '—'} pág./bloque)
        {t.eta_segundos ? ` · quedan ~${Math.ceil(t.eta_segundos)} s` : ''}
      </p>
      <p className="tenue">{t.fase}</p>
      <table style={{ maxWidth: 480 }}>
        <tbody>
          <tr><td>OF detectadas</td><td className="num">{c.ofs ?? 0}</td></tr>
          <tr><td>Aparatos detectados</td><td className="num">{c.aparatos ?? 0}</td></tr>
          <tr><td>Secciones detectadas</td><td className="num">{c.secciones ?? 0}</td></tr>
          <tr><td>Advertencias</td><td className="num">{c.advertencias ?? 0}</td></tr>
          <tr><td>Errores</td><td className="num">{c.errores ?? 0}</td></tr>
          <tr><td>Errores críticos</td><td className="num">{c.criticos ?? 0}</td></tr>
        </tbody>
      </table>
      {c.plan_bloques && <p className="pequeno tenue">Tamaño de bloque: {String(c.plan_bloques)}</p>}
      {t.error && <div className="mensaje error">{t.error}</div>}
      {t.estado === 'COMPLETADO' && <Link to={`/documentos/${t.documento_id}`}>Ver validación del documento →</Link>}
    </div>
  )
}

export default function Importacion() {
  const { datos, error, recargar } = useDatos(() => api.get<Doc[]>('/documentos'), [])
  const [carga, setCarga] = useState<Carga | null>(null)
  const [err, setErr] = useState<unknown>(null)
  const [subiendo, setSubiendo] = useState(false)
  const [arrastre, setArrastre] = useState(false)

  const subir = async (f: File | undefined) => {
    if (!f) return
    setSubiendo(true)
    setErr(null)
    setCarga(null)
    try {
      setCarga(await api.subir<Carga>('/documentos', f))
      recargar()
    } catch (e) {
      setErr(e)
    } finally {
      setSubiendo(false)
    }
  }

  return (
    <>
      <div className="cabecera">
        <div>
          <h1>Importar documentos de tanda</h1>
          <div className="sub">
            El PDF se procesa en segundo plano por bloques (no se carga entero en memoria). Si ya se cargó exactamente el mismo fichero no se reprocesa; si es otra versión de la misma
            tanda se procesa como nueva versión y se conserva el histórico. Para varias tandas a la vez, o para eliminarlas, usa <Link to="/tandas">Tandas</Link>.
          </div>
        </div>
      </div>
      <label
        className="panel"
        style={{ display: 'block', textAlign: 'center', padding: 30, borderStyle: 'dashed', borderColor: arrastre ? 'var(--acento)' : undefined, cursor: 'pointer' }}
        onDragOver={(e) => {
          e.preventDefault()
          setArrastre(true)
        }}
        onDragLeave={() => setArrastre(false)}
        onDrop={(e) => {
          e.preventDefault()
          setArrastre(false)
          subir(e.dataTransfer.files[0])
        }}
      >
        <strong>{subiendo ? 'Subiendo…' : 'Arrastra aquí el PDF de la tanda o pulsa para elegirlo'}</strong>
        <input type="file" accept="application/pdf" style={{ display: 'none' }} onChange={(e) => subir(e.target.files?.[0])} />
      </label>
      <MensajeError error={err} />
      {carga && (
        <div className={`mensaje ${carga.duplicado ? 'aviso' : 'ok'}`}>
          {carga.duplicado ? <strong>PDF duplicado. </strong> : carga.nueva_version ? <strong>Nueva versión {carga.version}. </strong> : null}
          {carga.mensaje} <Link to={`/documentos/${carga.documento_id}`}>Ver documento</Link>
        </div>
      )}
      {carga && carga.trabajo_id && !carga.duplicado && <Progreso trabajoId={carga.trabajo_id} onFin={recargar} />}

      <section className="panel" style={{ marginTop: 14 }}>
        <h2>Documentos cargados</h2>
        <MensajeError error={error} />
        {!datos ? (
          <Cargando />
        ) : (
          <table>
            <thead>
              <tr>
                <th>#</th>
                <th>Documento</th>
                <th>Clave</th>
                <th>Versión</th>
                <th className="num">Páginas</th>
                <th>Cargado</th>
                <th>Estado</th>
                <th className="num">OF</th>
                <th className="num">Errores</th>
                <th className="num">Advertencias</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {datos.map((d) => (
                <tr key={d.id}>
                  <td>{d.id}</td>
                  <td>
                    <Link to={`/documentos/${d.id}`}>{d.nombre}</Link>
                  </td>
                  <td>{d.clave ?? '—'}</td>
                  <td>v{d.version}</td>
                  <td className="num">{d.paginas ?? '—'}</td>
                  <td className="pequeno">
                    {fecha(d.fecha_carga)} · {d.usuario}
                  </td>
                  <td>
                    <span className="etiqueta">{d.estado}</span>
                  </td>
                  <td className="num">{d.resumen?.ofs ?? '—'}</td>
                  <td className="num">{d.resumen ? (d.resumen.criticas ?? 0) + (d.resumen.errores ?? 0) : '—'}</td>
                  <td className="num">{d.resumen?.advertencias ?? '—'}</td>
                  <td>
                    {['ERROR', 'CANCELADO'].includes(d.estado) && (
                      <button
                        title="Borra el documento para poder volver a cargarlo"
                        onClick={async () => {
                          try {
                            await api.del(`/documentos/${d.id}`)
                            recargar()
                          } catch (e) {
                            setErr(e)
                          }
                        }}
                      >
                        Eliminar
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
