import { useState } from 'react'
import { api } from '../api'

/** Priorizar de una vez todas las OF abiertas de una tanda o de un aparato, y replanificar. */
export default function Priorizar({ tanda_id, aparato_id, urgentes, total, onCambio }: { tanda_id?: number; aparato_id?: number; urgentes: number; total: number; onCambio: () => void }) {
  const [msg, setMsg] = useState<string | null>(null)
  const [ocupado, setOcupado] = useState(false)
  const [pendiente, setPendiente] = useState(false)
  const que = aparato_id ? 'del aparato' : 'de la tanda'
  const cambiar = async (urgente: boolean) => {
    setOcupado(true)
    try {
      const r = await api.post<{ cambiadas: number }>('/prioridad', { tanda_id, aparato_id, urgente, motivo: urgente ? `Prioridad manual ${que}` : `Fin de la prioridad manual ${que}` })
      setMsg(r.cambiadas ? `${r.cambiadas} OF ${urgente ? 'marcadas urgentes' : 'vuelven a su prioridad normal'}. El plan cambia al replanificar.` : 'No había nada que cambiar.')
      setPendiente(r.cambiadas > 0)
      onCambio()
    } catch (e) {
      setMsg(e instanceof Error ? e.message : String(e))
    } finally {
      setOcupado(false)
    }
  }
  const replanificar = async () => {
    setOcupado(true)
    try {
      await api.post('/plan/generar', { motivo: `Replanificación tras cambiar la prioridad ${que}` })
      setMsg('Plan regenerado con la nueva prioridad.')
      setPendiente(false)
      onCambio()
    } catch (e) {
      setMsg(e instanceof Error ? e.message : String(e))
    } finally {
      setOcupado(false)
    }
  }
  return (
    <div className="priorizar">
      <span className="pequeno tenue">
        {urgentes ? `${urgentes} de ${total} OF urgentes` : 'Prioridad normal'}
      </span>
      {urgentes < total && (
        <button disabled={ocupado} onClick={() => cambiar(true)}>
          Priorizar todo
        </button>
      )}
      {urgentes > 0 && (
        <button disabled={ocupado} onClick={() => cambiar(false)}>
          Quitar prioridad
        </button>
      )}
      {pendiente && (
        <button className="primario" disabled={ocupado} onClick={replanificar}>
          Replanificar ahora
        </button>
      )}
      {msg && <div className="pequeno">{msg}</div>}
    </div>
  )
}
