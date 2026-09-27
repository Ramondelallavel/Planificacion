import { useEffect, useState, type ReactNode } from 'react'
import { iniciarMotor, onMotor } from './motor'

/** Edición navegador: carga el motor (Python en WebAssembly) antes de mostrar la aplicación. */
export default function Arranque({ children }: { children: ReactNode }) {
  const [fase, setFase] = useState('Iniciando')
  const [pct, setPct] = useState(0)
  const [listo, setListo] = useState(false)
  const [ocupada, setOcupada] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const arrancar = (robar: boolean) => {
    setOcupada(false)
    iniciarMotor(robar).then(
      (r) => {
        if (r.ocupada) setOcupada(true)
        else {
          setListo(true)
          // que el navegador no borre los datos por falta de espacio (si lo permite)
          navigator.storage?.persist?.().catch(() => {})
        }
      },
      (e: Error) => setError(e.message),
    )
  }
  useEffect(() => {
    const quitar = onMotor((e) => {
      if (e.tipo === 'carga') {
        setFase(e.fase)
        setPct(e.pct)
      }
    })
    arrancar(false)
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
        ) : ocupada ? (
          <div className="mensaje aviso" style={{ marginTop: 18 }} role="alert">
            <strong>HIDRAL ya está abierta en otra pestaña o ventana de este navegador.</strong>
            <p className="pequeno">
              Los datos se guardan en este navegador y solo una pestaña puede usarlos a la vez; si no, unos cambios pisarían a otros. Sigue en la otra pestaña, o úsala aquí: la otra
              dejará de funcionar hasta que la recargues.
            </p>
            <div className="botones">
              <button className="primario" onClick={() => arrancar(true)}>
                Usar aquí
              </button>
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
