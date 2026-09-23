import { useState } from 'react'
import { api, type Sesion } from '../api'
import { NAVEGADOR } from '../motor'

// Usuarios que crea la configuración de ejemplo (clave «hidral»).
const USUARIOS_EJEMPLO: [string, string][] = [
  ['planificador', 'Planificador'],
  ['jefe', 'Jefe de equipo'],
  ['supervisor', 'Supervisor'],
  ['op01', 'Operario OP01'],
  ['op13', 'Operario OP13'],
  ['admin', 'Administrador'],
]
import { MensajeError } from '../componentes/comunes'

export default function Login({ onEntrar }: { onEntrar: (s: Sesion) => void }) {
  const [usuario, setUsuario] = useState('')
  const [clave, setClave] = useState('')
  const [error, setError] = useState<unknown>(null)
  const [enviando, setEnviando] = useState(false)
  return (
    <div className="login">
      <form
        className="panel"
        onSubmit={async (e) => {
          e.preventDefault()
          setEnviando(true)
          try {
            onEntrar(await api.post<Sesion>('/auth/login', { usuario, clave }))
          } catch (err) {
            setError(err)
          } finally {
            setEnviando(false)
          }
        }}
      >
        <h1>HIDRAL</h1>
        <p className="tenue">Planificación, programación y control de fabricación</p>
        <label className="campo">
          Usuario
          <input value={usuario} onChange={(e) => setUsuario(e.target.value)} autoFocus autoComplete="username" />
        </label>
        <label className="campo" style={{ marginTop: 10 }}>
          Contraseña
          <input type="password" value={clave} onChange={(e) => setClave(e.target.value)} autoComplete="current-password" />
        </label>
        <MensajeError error={error} />
        {NAVEGADOR && (
          <div style={{ marginTop: 14 }}>
            <p className="pequeno tenue">Instalación en este navegador con usuarios de ejemplo (clave «hidral»). Entra con un clic como:</p>
            <div className="botones">
              {USUARIOS_EJEMPLO.map(([u, nombre]) => (
                <button
                  key={u}
                  type="button"
                  disabled={enviando}
                  onClick={async () => {
                    setEnviando(true)
                    try {
                      onEntrar(await api.post<Sesion>('/auth/login', { usuario: u, clave: 'hidral' }))
                    } catch (err) {
                      setError(err)
                    } finally {
                      setEnviando(false)
                    }
                  }}
                >
                  {nombre}
                </button>
              ))}
            </div>
          </div>
        )}
        <button className="primario" style={{ marginTop: 14, width: '100%', justifyContent: 'center' }} disabled={enviando || !usuario}>
          Entrar
        </button>
      </form>
    </div>
  )
}
