import { useEffect, useState, type ReactNode } from 'react'
import { iniciarMotor, onMotor } from './motor'

/** Edición navegador: carga el motor (Python en WebAssembly) antes de mostrar la aplicación. */
export default function Arranque({ children }: { children: ReactNode }) {
  const [fase, setFase] = useState('Iniciando')
  const [pct, setPct] = useState(0)
  const [listo, setListo] = useState(false)
  const [error, setError] = useState<string | null>(null)
  useEffect(() => {
    const quitar = onMotor((e) => {
      if (e.tipo === 'carga') {
        setFase(e.fase)
        setPct(e.pct)
      }
    })
    iniciarMotor().then(
      () => setListo(true),
      (e: Error) => setError(e.message),
    )
    return () => {
      quitar()
    }
  }, [])
  if (listo) return <>{children}</>
  return (
    <div className="arranque">
      <div className="arranque-caja">
        <div className="marca-arranque">HIDRAL</div>
        <div className="tenue">Planificación, programación y control de fabricación</div>
        {error ? (
          <div className="mensaje error" style={{ marginTop: 18 }}>
            <strong>No se pudo iniciar el motor de planificación.</strong>
            <div className="pequeno" style={{ whiteSpace: 'pre-wrap', marginTop: 6 }}>
              {error}
            </div>
          </div>
        ) : (
          <>
            <div className="arranque-barra" role="progressbar" aria-valuenow={pct} aria-valuemin={0} aria-valuemax={100}>
              <div style={{ width: `${pct}%` }} />
            </div>
            <div className="arranque-fase">{fase}…</div>
            <p className="pequeno tenue">
              Todo se ejecuta en este navegador: el motor completo (lectura de PDF, planificador, replanificación) y tus datos, que se guardan aquí. La primera vez descarga unos 40 MB; después
              arranca en segundos.
            </p>
          </>
        )}
      </div>
    </div>
  )
}
