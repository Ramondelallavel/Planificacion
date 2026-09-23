import { useState } from 'react'
import { api, type Sesion } from '../api'
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
        <button className="primario" style={{ marginTop: 14, width: '100%', justifyContent: 'center' }} disabled={enviando || !usuario}>
          Entrar
        </button>
      </form>
    </div>
  )
}
