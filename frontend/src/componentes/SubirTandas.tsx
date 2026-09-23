import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../api'
import type { Trabajo } from '../paginas/Importacion'

interface Carga {
  documento_id: number
  trabajo_id: number | null
  duplicado: boolean
  nueva_version: boolean
  version: number
  mensaje: string
}
interface Fila {
  nombre: string
  carga?: Carga
  trabajo?: Trabajo
  error?: string
}

const FIN = ['COMPLETADO', 'ERROR', 'CANCELADO']

/** Añadir una o varias tandas arrastrando sus PDF; al terminar, replanificar con ellas. */
export default function SubirTandas({ onCambio }: { onCambio: () => void }) {
  const [filas, setFilas] = useState<Fila[]>([])
  const [arrastre, setArrastre] = useState(false)
  const [plan, setPlan] = useState<string | null>(null)
  const [replanificando, setReplanificando] = useState(false)

  // seguimiento del procesamiento de cada PDF
  useEffect(() => {
    const vivos = filas.filter((f) => f.carga?.trabajo_id && !f.carga.duplicado && !FIN.includes(f.trabajo?.estado ?? ''))
    if (!vivos.length) return
    const t = window.setTimeout(async () => {
      const nuevos = await Promise.all(
        filas.map(async (f) => {
          if (!f.carga?.trabajo_id || f.carga.duplicado || FIN.includes(f.trabajo?.estado ?? '')) return f
          try {
            return { ...f, trabajo: await api.get<Trabajo>(`/trabajos/${f.carga.trabajo_id}`) }
          } catch {
            return f
          }
        }),
      )
      setFilas(nuevos)
      if (nuevos.some((f, i) => f.trabajo?.estado === 'COMPLETADO' && filas[i].trabajo?.estado !== 'COMPLETADO')) onCambio()
    }, 1000)
    return () => window.clearTimeout(t)
  }, [filas, onCambio])

  const subir = async (ficheros: FileList | null) => {
    const pdfs = [...(ficheros ?? [])].filter((f) => f.type === 'application/pdf' || f.name.toLowerCase().endsWith('.pdf'))
    if (!pdfs.length) return
    setPlan(null)
    const base = filas.length
    setFilas((x) => [...x, ...pdfs.map((f) => ({ nombre: f.name }))])
    for (const [i, f] of pdfs.entries()) {
      try {
        const carga = await api.subir<Carga>('/documentos', f)
        setFilas((x) => x.map((y, k) => (k === base + i ? { ...y, carga } : y)))
      } catch (e) {
        setFilas((x) => x.map((y, k) => (k === base + i ? { ...y, error: e instanceof Error ? e.message : String(e) } : y)))
      }
    }
  }

  const nuevas = filas.filter((f) => f.trabajo?.estado === 'COMPLETADO').length
  const procesando = filas.some((f) => !f.error && (!f.carga || (f.carga.trabajo_id && !f.carga.duplicado && !FIN.includes(f.trabajo?.estado ?? ''))))
  const replanificar = async () => {
    setReplanificando(true)
    try {
      const r = await api.post<{ plan_id: number; kpis: { planificadas: number; no_planificadas: number } }>('/plan/generar', { motivo: `Nuevas tandas: ${filas.map((f) => f.nombre).join(', ')}`.slice(0, 400) })
      setPlan(`Plan regenerado: ${r.kpis.planificadas} operaciones planificadas${r.kpis.no_planificadas ? `, ${r.kpis.no_planificadas} no planificables` : ''}.`)
      setFilas([])
      onCambio()
    } catch (e) {
      setPlan(e instanceof Error ? e.message : String(e))
    } finally {
      setReplanificando(false)
    }
  }

  return (
    <section className="panel">
      <label
        className={`zona-subida ${arrastre ? 'activa' : ''}`}
        onDragOver={(e) => {
          e.preventDefault()
          setArrastre(true)
        }}
        onDragLeave={() => setArrastre(false)}
        onDrop={(e) => {
          e.preventDefault()
          setArrastre(false)
          subir(e.dataTransfer.files)
        }}
      >
        <strong>＋ Añadir tandas</strong>
        <span className="pequeno tenue">Arrastra aquí uno o varios PDF de tanda, o pulsa para elegirlos. Un PDF ya cargado no se duplica; otra versión de la misma tanda la actualiza.</span>
        <input id="subir-tandas" type="file" accept="application/pdf" multiple style={{ display: 'none' }} onChange={(e) => subir(e.target.files)} />
      </label>
      {filas.length > 0 && (
        <table className="subidas">
          <tbody>
            {filas.map((f, i) => {
              const t = f.trabajo
              const estado = f.error
                ? f.error
                : !f.carga
                  ? 'Subiendo…'
                  : f.carga.duplicado
                    ? 'Ya estaba cargado: no se reprocesa'
                    : !f.carga.trabajo_id
                      ? f.carga.mensaje
                      : t?.estado === 'COMPLETADO'
                        ? `Listo: ${t.contadores.ofs ?? 0} OF, ${t.contadores.aparatos ?? 0} aparatos${Number(t.contadores.criticos) ? ` · ${t.contadores.criticos} errores críticos que revisar` : ''}`
                        : t?.estado === 'ERROR'
                          ? `Error: ${t.error ?? ''}`
                          : `Procesando… ${t ? `${t.porcentaje}% (${t.paginas_procesadas}/${t.paginas_totales} págs.)` : ''}`
              return (
                <tr key={i}>
                  <td>{f.nombre}</td>
                  <td className="pequeno">
                    {estado}
                    {!f.error && t && !FIN.includes(t.estado) && (
                      <div className="progreso fino">
                        <div style={{ width: `${t.porcentaje}%` }} />
                      </div>
                    )}
                  </td>
                  <td className="pequeno">{f.carga && <Link to={`/documentos/${f.carga.documento_id}`}>validación</Link>}</td>
                </tr>
              )
            })}
          </tbody>
        </table>
      )}
      {nuevas > 0 && !procesando && (
        <div className="botones" style={{ marginTop: 8 }}>
          <button className="primario" disabled={replanificando} onClick={replanificar}>
            {replanificando ? 'Replanificando…' : `Replanificar con ${nuevas === 1 ? 'la nueva tanda' : `las ${nuevas} tandas nuevas`}`}
          </button>
          <button onClick={() => setFilas([])}>Cerrar</button>
        </div>
      )}
      {plan && <div className="mensaje ok">{plan}</div>}
    </section>
  )
}
