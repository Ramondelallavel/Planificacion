import { useEffect, useState } from 'react'
import { onMotor } from '../motor'
import { crearCopia, descargar } from '../plataforma'

/** Edición navegador: avisos del motor que no pueden pasar desapercibidos (no se pudo guardar,
 * el motor se ha detenido, los datos se han abierto en otra pestaña). */
export default function EstadoMotor() {
  const [aviso, setAviso] = useState<string | null>(null)
  const [desplazada, setDesplazada] = useState(false)
  const [msg, setMsg] = useState('')
  useEffect(
    () =>
      onMotor((e) => {
        if (e.tipo === 'aviso') setAviso(e.mensaje)
        else if (e.tipo === 'desplazada') setDesplazada(true)
        else if (e.tipo === 'guardado') setAviso(null)
      }),
    [],
  )
  const copia = async () => {
    try {
      const c = await crearCopia()
      setMsg(await descargar(`hidral-copia-${c.fecha.slice(0, 10)}.json`, JSON.stringify(c), 'application/json'))
    } catch (e) {
      setMsg((e as Error).message)
    }
  }
  if (desplazada)
    return (
      <div className="modal-fondo" role="alertdialog" aria-modal="true" aria-labelledby="titulo-desplazada">
        <div className="modal" style={{ width: 'min(560px, 100%)' }}>
          <h2 id="titulo-desplazada">HIDRAL se ha abierto en otra pestaña</h2>
          <p>Los datos de este navegador los está usando ahora la otra pestaña. Esta ya no guarda cambios, para que no se pisen.</p>
          <p className="pequeno tenue">Si aquí tenías algo sin guardar, descarga una copia antes de recargar.</p>
          <div className="botones">
            <button className="primario" onClick={() => window.location.reload()}>
              Recargar esta pestaña
            </button>
            <button onClick={copia}>Descargar copia de lo que ves</button>
          </div>
          {msg && <div className="pequeno">{msg}</div>}
        </div>
      </div>
    )
  if (!aviso) return null
  return (
    <div className="mensaje error aviso-motor" role="alert">
      <span>{aviso}</span>
      <button className="enlace" onClick={() => setAviso(null)} aria-label="Cerrar aviso">
        ✕
      </button>
    </div>
  )
}
