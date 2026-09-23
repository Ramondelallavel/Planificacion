import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { api } from '../api'
import { MensajeError, Modal } from './comunes'

/** "2026-W41" (input type=week) o "202641" → "202641" */
export function aSemana(v: string): string {
  const m = /^(\d{4})-?W?(\d{1,2})$/i.exec(v.trim())
  return m ? `${m[1]}${m[2].padStart(2, '0')}` : v.trim()
}
export const aInputSemana = (codigo: string | null) => (codigo && codigo.length === 6 ? `${codigo.slice(0, 4)}-W${codigo.slice(4)}` : '')

export function CambiarSemana({ titulo, actual, ruta, onCerrar, onHecho }: { titulo: string; actual: string | null; ruta: string; onCerrar: () => void; onHecho: () => void }) {
  const [semana, setSemana] = useState(aInputSemana(actual))
  const [motivo, setMotivo] = useState('')
  const [err, setErr] = useState<unknown>(null)
  return (
    <Modal titulo={titulo} onCerrar={onCerrar}>
      <p className="pequeno tenue">Cambia la semana de fabricación comprometida (y la de sus OF). El riesgo y el plan se recalculan al replanificar.</p>
      <div className="formulario">
        <label className="campo">
          Semana de fabricación
          <input id="semana-nueva" type="week" value={semana} onChange={(e) => setSemana(e.target.value)} />
        </label>
        <label className="campo">
          Motivo
          <input value={motivo} onChange={(e) => setMotivo(e.target.value)} placeholder="el cliente adelanta la entrega…" />
        </label>
      </div>
      <MensajeError error={err} />
      <div className="botones" style={{ marginTop: 8 }}>
        <button
          className="primario"
          disabled={!semana}
          onClick={async () => {
            try {
              await api.patch(ruta, { semana: aSemana(semana), motivo: motivo || null })
              onHecho()
            } catch (e) {
              setErr(e)
            }
          }}
        >
          Guardar
        </button>
        <button onClick={onCerrar}>Cancelar</button>
      </div>
    </Modal>
  )
}

interface TandaBasica {
  id: number
  numero: string
  producto: string | null
  semana: string | null
  estado: string
  incluida_en_plan: boolean
}

/** Botones de gestión de una tanda: editar, sacar del plan, archivar, eliminar. */
export default function GestionTanda({ t, onCambio }: { t: TandaBasica; onCambio: () => void }) {
  const [modal, setModal] = useState<'editar' | 'eliminar' | null>(null)
  const [err, setErr] = useState<unknown>(null)
  const cambiar = async (cuerpo: Record<string, unknown>) => {
    setErr(null)
    try {
      await api.patch(`/tandas/${t.id}`, cuerpo)
      onCambio()
    } catch (e) {
      setErr(e)
    }
  }
  return (
    <div className="gestion-tanda">
      <div className="botones">
        <button onClick={() => setModal('editar')}>Editar</button>
        {t.estado === 'ACTIVA' &&
          (t.incluida_en_plan ? (
            <button onClick={() => cambiar({ incluida_en_plan: false, motivo: 'Excluida manualmente del plan' })}>Sacar del plan</button>
          ) : (
            <button onClick={() => cambiar({ incluida_en_plan: true, motivo: 'Incluida en el plan' })}>Meter en el plan</button>
          ))}
        {t.estado === 'ACTIVA' ? (
          <button onClick={() => cambiar({ estado: 'ARCHIVADA', motivo: 'Archivada' })}>Archivar</button>
        ) : (
          <button onClick={() => cambiar({ estado: 'ACTIVA', motivo: 'Reactivada' })}>Reactivar</button>
        )}
        <button className="peligro" onClick={() => setModal('eliminar')}>
          Eliminar
        </button>
      </div>
      <MensajeError error={err} />
      {modal === 'editar' && <EditarTanda t={t} onCerrar={() => setModal(null)} onHecho={() => (setModal(null), onCambio())} />}
      {modal === 'eliminar' && <EliminarTanda t={t} onCerrar={() => setModal(null)} onArchivada={() => (setModal(null), onCambio())} />}
    </div>
  )
}

function EditarTanda({ t, onCerrar, onHecho }: { t: TandaBasica; onCerrar: () => void; onHecho: () => void }) {
  const [producto, setProducto] = useState(t.producto ?? '')
  const [semana, setSemana] = useState(aInputSemana(t.semana))
  const [motivo, setMotivo] = useState('')
  const [err, setErr] = useState<unknown>(null)
  return (
    <Modal titulo={`Editar tanda ${t.numero}`} onCerrar={onCerrar}>
      <div className="formulario">
        <label className="campo">
          Producto
          <input value={producto} onChange={(e) => setProducto(e.target.value)} />
        </label>
        <label className="campo">
          Semana de fabricación (tanda y todos sus aparatos)
          <input id="semana-tanda" type="week" value={semana} onChange={(e) => setSemana(e.target.value)} />
        </label>
        <label className="campo">
          Motivo del cambio
          <input value={motivo} onChange={(e) => setMotivo(e.target.value)} />
        </label>
      </div>
      <MensajeError error={err} />
      <div className="botones" style={{ marginTop: 8 }}>
        <button
          className="primario"
          onClick={async () => {
            try {
              const nueva = semana ? aSemana(semana) : null
              await api.patch(`/tandas/${t.id}`, { producto, semana: nueva && nueva !== t.semana ? nueva : null, motivo: motivo || null })
              onHecho()
            } catch (e) {
              setErr(e)
            }
          }}
        >
          Guardar
        </button>
        <button onClick={onCerrar}>Cancelar</button>
      </div>
    </Modal>
  )
}

function EliminarTanda({ t, onCerrar, onArchivada }: { t: TandaBasica; onCerrar: () => void; onArchivada: () => void }) {
  const [motivo, setMotivo] = useState('')
  const [err, setErr] = useState<string | null>(null)
  const [ocupado, setOcupado] = useState(false)
  const navegar = useNavigate()
  return (
    <Modal titulo={`Eliminar la tanda ${t.numero}`} onCerrar={onCerrar}>
      <p>
        Se borran la tanda, sus aparatos, bultos, OF y operaciones, y el PDF del que salieron (podrás volver a importarlo). El plan se regenera sin ella. <strong>No se puede deshacer</strong>
        {' '}(salvo con una copia de «Datos y copias»).
      </p>
      <p className="pequeno tenue">Si solo quieres que deje de planificarse, archívala: se conserva todo y puedes reactivarla.</p>
      <label className="campo">
        Motivo
        <input id="motivo-eliminar" value={motivo} onChange={(e) => setMotivo(e.target.value)} placeholder="pedido anulado, cargada por error…" />
      </label>
      {err && <div className="mensaje error">{err}</div>}
      <div className="botones" style={{ marginTop: 8 }}>
        <button
          className="peligro"
          disabled={ocupado}
          onClick={async () => {
            setOcupado(true)
            try {
              await api.del(`/tandas/${t.id}?motivo=${encodeURIComponent(motivo)}`)
              navegar('/tandas')
            } catch (e) {
              setErr(e instanceof Error ? e.message : String(e))
            } finally {
              setOcupado(false)
            }
          }}
        >
          {ocupado ? 'Eliminando…' : 'Eliminar definitivamente'}
        </button>
        {err && t.estado === 'ACTIVA' && (
          <button
            onClick={async () => {
              await api.patch(`/tandas/${t.id}`, { estado: 'ARCHIVADA', motivo: motivo || 'Archivada: tenía trabajo fichado' })
              onArchivada()
            }}
          >
            Archivarla
          </button>
        )}
        <button onClick={onCerrar}>Cancelar</button>
      </div>
    </Modal>
  )
}
