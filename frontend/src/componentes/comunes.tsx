import { useCallback, useEffect, useRef, useState, type ReactNode } from 'react'
import { ErrorApi } from '../api'
import { NIVEL_TEXTO } from '../formato'
import type { Explicacion, Nivel } from '../tipos'

export function Riesgo({ nivel, texto }: { nivel: Nivel | string | null | undefined; texto?: boolean }) {
  if (!nivel) return <span className="nd">—</span>
  return (
    <span className={`riesgo ${nivel}`} title={NIVEL_TEXTO[nivel] ?? nivel}>
      {texto ? NIVEL_TEXTO[nivel] ?? nivel : nivel}
    </span>
  )
}

export function Kpi({ valor, etiqueta, nivel }: { valor: ReactNode; etiqueta: string; nivel?: Nivel | string }) {
  return (
    <div className={`kpi ${nivel ?? ''}`}>
      <div className="valor">{valor}</div>
      <div className="etiqueta">{etiqueta}</div>
    </div>
  )
}

export function Modal({ titulo, onCerrar, children }: { titulo: string; onCerrar: () => void; children: ReactNode }) {
  useEffect(() => {
    const f = (e: KeyboardEvent) => e.key === 'Escape' && onCerrar()
    window.addEventListener('keydown', f)
    return () => window.removeEventListener('keydown', f)
  }, [onCerrar])
  return (
    <div className="modal-fondo" onMouseDown={(e) => e.target === e.currentTarget && onCerrar()}>
      <div className="modal" role="dialog" aria-label={titulo}>
        <button className="cerrar" onClick={onCerrar} aria-label="Cerrar">
          ✕
        </button>
        <h2>{titulo}</h2>
        {children}
      </div>
    </div>
  )
}

export function MensajeError({ error }: { error: unknown }) {
  if (!error) return null
  if (error instanceof ErrorApi) {
    return (
      <div className="mensaje error">
        <strong>{error.message}</strong>
        {error.errores.length > 0 && (
          <ul>
            {error.errores.map((e, i) => (
              <li key={i}>{e}</li>
            ))}
          </ul>
        )}
      </div>
    )
  }
  return <div className="mensaje error">{String((error as Error)?.message ?? error)}</div>
}

/** Carga de datos con recarga manual y opcionalmente periódica. */
export function useDatos<T>(cargar: () => Promise<T>, deps: unknown[], intervaloMs?: number) {
  const [datos, setDatos] = useState<T | null>(null)
  const [error, setError] = useState<unknown>(null)
  const [cargando, setCargando] = useState(true)
  const ref = useRef(cargar)
  ref.current = cargar
  const recargar = useCallback(async () => {
    setCargando(true)
    try {
      setDatos(await ref.current())
      setError(null)
    } catch (e) {
      setError(e)
    } finally {
      setCargando(false)
    }
  }, [])
  useEffect(() => {
    recargar()
    if (!intervaloMs) return
    const t = window.setInterval(recargar, intervaloMs)
    return () => window.clearInterval(t)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps)
  return { datos, error, cargando, recargar, setDatos }
}

export function Cargando() {
  return <p className="tenue">Cargando…</p>
}

export function ExplicacionDecision({ e }: { e: Explicacion | null | undefined }) {
  if (!e) return <p className="nd">Sin explicación registrada.</p>
  const p = e.prioridad
  return (
    <div className="explicacion">
      {p && (
        <>
          <h3>
            Por qué se ha priorizado (índice {p.valor.toLocaleString('es-ES')} / 100)
          </h3>
          <ol>
            {p.motivos.map((m, i) => (
              <li key={i}>{m}</li>
            ))}
          </ol>
          {p.datos_no_disponibles.length > 0 && <p className="nd">DATO NO DISPONIBLE: {p.datos_no_disponibles.join(', ')}</p>}
          <details>
            <summary className="pequeno">Contribución de cada factor (pesos configurables)</summary>
            <div className="factores" style={{ marginTop: 8 }}>
              {p.factores.map((f) => (
                <FactorFila key={f.factor} nombre={f.nombre} valor={f.valor} peso={f.peso} contribucion={f.contribucion} />
              ))}
            </div>
          </details>
        </>
      )}
      <h3 style={{ marginTop: 12 }}>Recurso y operario</h3>
      <ul className="lista-plana">
        <li>
          <strong>{e.recurso.codigo}</strong>: {e.recurso.motivo}
          {e.cuello_botella && <span className="etiqueta" style={{ marginLeft: 6 }}>cuello de botella</span>}
        </li>
        {e.operario && (
          <li>
            <strong>{e.operario.nombre}</strong> ({e.operario.codigo}): {e.operario.motivo}
          </li>
        )}
        <li>
          Inicio condicionado por: {e.inicio_condicionado_por.join('; ')}
        </li>
        {e.setup && <li>Setup: {e.setup}</li>}
        {e.provisional && (
          <li>
            <span className="riesgo AMARILLO">Provisional</span> {e.provisional}
          </li>
        )}
        {e.cambio_manual && (
          <li>
            Cambio manual de <strong>{e.cambio_manual.usuario}</strong>: {e.cambio_manual.motivo}
          </li>
        )}
      </ul>
      {e.alternativas.length > 0 && (
        <p className="pequeno tenue">
          Alternativas evaluadas: {e.alternativas.map((a) => `${a.recurso}${a.operario ? '/' + a.operario : ''} (fin ${new Date(a.fin).toLocaleString('es-ES')})`).join(' · ')}
        </p>
      )}
    </div>
  )
}

function FactorFila({ nombre, valor, peso, contribucion }: { nombre: string; valor: number; peso: number; contribucion: number }) {
  return (
    <>
      <span title={`valor ${valor} × peso ${peso}`}>{nombre}</span>
      <div className="barra-f">
        <div style={{ width: `${Math.min(100, valor * 100)}%` }} />
      </div>
      <span className="num">{contribucion}</span>
    </>
  )
}
