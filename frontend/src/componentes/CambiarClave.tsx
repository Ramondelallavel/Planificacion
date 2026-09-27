import { useState } from 'react'
import { api } from '../api'
import { MensajeError, Modal } from './comunes'

/** Cambio de la propia contraseña (mínimo 8 caracteres). */
export default function CambiarClave({ onCerrar }: { onCerrar: () => void }) {
  const [actual, setActual] = useState('')
  const [nueva, setNueva] = useState('')
  const [repetida, setRepetida] = useState('')
  const [err, setErr] = useState<unknown>(null)
  const [hecho, setHecho] = useState(false)
  const distinta = repetida.length > 0 && nueva !== repetida
  return (
    <Modal titulo="Cambiar mi contraseña" onCerrar={onCerrar}>
      {hecho ? (
        <>
          <div className="mensaje ok">Contraseña cambiada. La próxima vez entra con la nueva.</div>
          <button onClick={onCerrar}>Cerrar</button>
        </>
      ) : (
        <form
          onSubmit={async (e) => {
            e.preventDefault()
            setErr(null)
            try {
              await api.post('/auth/clave', { actual, nueva })
              setHecho(true)
            } catch (x) {
              setErr(x)
            }
          }}
        >
          <div className="formulario">
            <label className="campo">
              Contraseña actual
              <input type="password" autoComplete="current-password" value={actual} onChange={(e) => setActual(e.target.value)} />
            </label>
            <label className="campo">
              Nueva (mínimo 8 caracteres)
              <input type="password" autoComplete="new-password" value={nueva} onChange={(e) => setNueva(e.target.value)} />
            </label>
            <label className="campo">
              Repite la nueva
              <input type="password" autoComplete="new-password" value={repetida} onChange={(e) => setRepetida(e.target.value)} />
            </label>
          </div>
          {distinta && <div className="pequeno riesgo ROJO">No coinciden</div>}
          <MensajeError error={err} />
          <div className="botones" style={{ marginTop: 8 }}>
            <button className="primario" type="submit" disabled={!actual || nueva.length < 8 || nueva !== repetida}>
              Cambiar
            </button>
            <button type="button" onClick={onCerrar}>
              Cancelar
            </button>
          </div>
        </form>
      )}
    </Modal>
  )
}
