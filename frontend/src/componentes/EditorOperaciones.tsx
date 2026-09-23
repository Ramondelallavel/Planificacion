import { useState } from 'react'
import { api } from '../api'
import type { Recurso } from '../tipos'
import { MensajeError, Modal, useDatos } from './comunes'

export interface OpEditable {
  id: number
  secuencia: number
  tipo: string
  descripcion: string | null
  seccion: string | null
  recurso_preferido: string | null
  duracion_estimada_min: number | null
  estado: string
}

const useRecursos = () => useDatos(() => api.get<Recurso[]>('/recursos'), [])

/** Selector de máquina (vacío = cualquiera de la sección) y de sección. */
function MaquinaYSeccion({ tipo, maquina, seccion, onCambio }: { tipo: string; maquina: string; seccion: string; onCambio: (m: string, s: string) => void }) {
  const recursos = useRecursos().datos ?? []
  const secciones = [...new Set(recursos.map((r) => r.seccion).filter(Boolean))].sort() as string[]
  const validas = recursos.filter((r) => r.activo && r.tipo !== 'PROGRAMACION' && (!seccion || r.seccion === seccion))
  const aviso = maquina && tipo && (() => {
    const r = recursos.find((x) => x.codigo === maquina)
    return r && r.operaciones?.length && !r.operaciones.includes(tipo.toUpperCase()) ? `${r.codigo} no tiene ${tipo.toUpperCase()} entre sus operaciones (${r.operaciones.join(', ')})` : null
  })()
  return (
    <>
      <label className="campo">
        Sección (equipo)
        <select value={seccion} onChange={(e) => onCambio('', e.target.value)}>
          <option value="">—</option>
          {secciones.map((s) => (
            <option key={s}>{s}</option>
          ))}
        </select>
      </label>
      <label className="campo">
        Máquina
        <select value={maquina} onChange={(e) => onCambio(e.target.value, recursos.find((r) => r.codigo === e.target.value)?.seccion ?? seccion)}>
          <option value="">cualquiera de la sección</option>
          {validas.map((r) => (
            <option key={r.id} value={r.codigo}>
              {r.codigo} · {r.nombre}
            </option>
          ))}
        </select>
        {aviso && <span className="pequeno riesgo NARANJA">{aviso}</span>}
      </label>
    </>
  )
}

export function EditarOperacion({ op, onCerrar, onHecho }: { op: OpEditable; onCerrar: () => void; onHecho: () => void }) {
  const [minutos, setMinutos] = useState(String(op.duracion_estimada_min ?? ''))
  const [maquina, setMaquina] = useState(op.recurso_preferido ?? '')
  const [seccion, setSeccion] = useState(op.seccion ?? '')
  const [descripcion, setDescripcion] = useState(op.descripcion ?? '')
  const [motivo, setMotivo] = useState('')
  const [err, setErr] = useState<unknown>(null)
  return (
    <Modal titulo={`Operación ${op.secuencia} · ${op.tipo}`} onCerrar={onCerrar}>
      <p className="pequeno tenue">Lo que cambies aquí manda sobre los tiempos estándar y no se pierde al recalcularlos. El plan cambia al replanificar.</p>
      <div className="formulario">
        <label className="campo">
          Duración (minutos)
          <input id="op-minutos" type="number" min="1" value={minutos} onChange={(e) => setMinutos(e.target.value)} />
        </label>
        <MaquinaYSeccion
          tipo={op.tipo}
          maquina={maquina}
          seccion={seccion}
          onCambio={(m, s) => {
            setMaquina(m)
            setSeccion(s)
          }}
        />
        <label className="campo">
          Descripción
          <input value={descripcion} onChange={(e) => setDescripcion(e.target.value)} />
        </label>
        <label className="campo">
          Motivo
          <input value={motivo} onChange={(e) => setMotivo(e.target.value)} placeholder="pieza más compleja, otra máquina libre…" />
        </label>
      </div>
      <MensajeError error={err} />
      <div className="botones" style={{ marginTop: 8 }}>
        <button
          className="primario"
          onClick={async () => {
            try {
              const cuerpo: Record<string, unknown> = { descripcion, motivo: motivo || null }
              if (minutos && Number(minutos) !== op.duracion_estimada_min) cuerpo.minutos = Number(minutos)
              if (maquina !== (op.recurso_preferido ?? '')) cuerpo.maquina = maquina || null
              if (seccion && seccion !== op.seccion) cuerpo.seccion = seccion
              await api.patch(`/operaciones/${op.id}`, cuerpo)
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

export function NuevaOperacion({ ofId, ops, seccionOF, onCerrar, onHecho }: { ofId: number; ops: OpEditable[]; seccionOF: string | null; onCerrar: () => void; onHecho: () => void }) {
  const [tipo, setTipo] = useState('')
  const [minutos, setMinutos] = useState('')
  const [maquina, setMaquina] = useState('')
  const [seccion, setSeccion] = useState(seccionOF ?? '')
  const [despues, setDespues] = useState(ops.length ? String(ops[ops.length - 1].id) : '')
  const [motivo, setMotivo] = useState('')
  const [err, setErr] = useState<unknown>(null)
  return (
    <Modal titulo="Añadir operación" onCerrar={onCerrar}>
      <div className="formulario">
        <label className="campo">
          Tipo de operación
          <input id="nueva-op-tipo" value={tipo} onChange={(e) => setTipo(e.target.value)} placeholder="SOLDADURA, RETRABAJO, PINTURA…" list="tipos-operacion" />
          <datalist id="tipos-operacion">
            {['CORTE', 'CORTE_LASER', 'PLEGADO', 'SOLDADURA', 'MONTAJE', 'MONTAJE_ELECTRICO', 'CABLEADO', 'PINTURA', 'PRUEBA', 'EMBALAJE', 'RETRABAJO', 'MECANIZADO', 'PREPARACION'].map((t) => (
              <option key={t} value={t} />
            ))}
          </datalist>
        </label>
        <label className="campo">
          Duración (minutos)
          <input id="nueva-op-minutos" type="number" min="1" value={minutos} onChange={(e) => setMinutos(e.target.value)} />
        </label>
        <MaquinaYSeccion
          tipo={tipo}
          maquina={maquina}
          seccion={seccion}
          onCambio={(m, s) => {
            setMaquina(m)
            setSeccion(s)
          }}
        />
        <label className="campo">
          Va después de
          <select value={despues} onChange={(e) => setDespues(e.target.value)}>
            <option value="">al principio</option>
            {ops.map((o) => (
              <option key={o.id} value={o.id}>
                {o.secuencia} · {o.tipo}
              </option>
            ))}
          </select>
        </label>
        <label className="campo">
          Motivo
          <input value={motivo} onChange={(e) => setMotivo(e.target.value)} />
        </label>
      </div>
      <MensajeError error={err} />
      <div className="botones" style={{ marginTop: 8 }}>
        <button
          className="primario"
          disabled={!tipo || !minutos || (!seccion && !maquina)}
          onClick={async () => {
            try {
              // despues_de 0 = al principio
              await api.post(`/ofs/${ofId}/operaciones`, { tipo, minutos: Number(minutos), maquina: maquina || null, seccion: seccion || null, despues_de: despues ? Number(despues) : 0, motivo: motivo || null })
              onHecho()
            } catch (e) {
              setErr(e)
            }
          }}
        >
          Añadir
        </button>
        <button onClick={onCerrar}>Cancelar</button>
      </div>
    </Modal>
  )
}

interface FilaOp {
  tipo: string
  minutos: string
  maquina: string
  seccion: string
}

/** OF creada a mano: retrabajos, reparaciones, pedidos sueltos… */
export function NuevaOF({ onCerrar, onHecho }: { onCerrar: () => void; onHecho: (of: { id: number; numero: string }) => void }) {
  const tandas = useDatos(() => api.get<{ id: number; numero: string; estado: string; producto: string | null }[]>('/tandas'), [])
  const [f, setF] = useState({ numero: '', descripcion: '', tanda_id: '', semana: '', urgente: false, motivo: '' })
  const [ops, setOps] = useState<FilaOp[]>([{ tipo: '', minutos: '', maquina: '', seccion: '' }])
  const [err, setErr] = useState<unknown>(null)
  const valido = ops.every((o) => o.tipo && Number(o.minutos) > 0 && (o.seccion || o.maquina))
  return (
    <Modal titulo="Nueva OF (sin PDF)" onCerrar={onCerrar}>
      <p className="pequeno tenue">Para trabajo que no viene en ningún PDF: retrabajos, reparaciones, pedidos sueltos. Sin tanda, va a la tanda «VARIOS».</p>
      <div className="formulario">
        <label className="campo">
          Número (vacío = automático)
          <input value={f.numero} onChange={(e) => setF({ ...f, numero: e.target.value })} placeholder="M00001" />
        </label>
        <label className="campo">
          Descripción
          <input id="nueva-of-descripcion" value={f.descripcion} onChange={(e) => setF({ ...f, descripcion: e.target.value })} />
        </label>
        <label className="campo">
          Tanda
          <select value={f.tanda_id} onChange={(e) => setF({ ...f, tanda_id: e.target.value })}>
            <option value="">VARIOS (trabajos sueltos)</option>
            {(tandas.datos ?? [])
              .filter((t) => t.estado === 'ACTIVA' && t.numero !== 'VARIOS')
              .map((t) => (
                <option key={t.id} value={t.id}>
                  {t.numero} {t.producto ? `· ${t.producto}` : ''}
                </option>
              ))}
          </select>
        </label>
        <label className="campo">
          Semana (vacío = la de la tanda)
          <input type="week" value={f.semana} onChange={(e) => setF({ ...f, semana: e.target.value })} />
        </label>
      </div>
      <h3>Operaciones, en orden</h3>
      {ops.map((o, i) => (
        <div key={i} className="formulario fila-op">
          <label className="campo">
            Tipo
            <input value={o.tipo} list="tipos-operacion-of" onChange={(e) => setOps(ops.map((x, k) => (k === i ? { ...x, tipo: e.target.value } : x)))} />
          </label>
          <label className="campo">
            Minutos
            <input type="number" min="1" value={o.minutos} onChange={(e) => setOps(ops.map((x, k) => (k === i ? { ...x, minutos: e.target.value } : x)))} />
          </label>
          <MaquinaYSeccion tipo={o.tipo} maquina={o.maquina} seccion={o.seccion} onCambio={(m, s) => setOps(ops.map((x, k) => (k === i ? { ...x, maquina: m, seccion: s } : x)))} />
          {ops.length > 1 && (
            <button className="enlace" onClick={() => setOps(ops.filter((_, k) => k !== i))}>
              quitar
            </button>
          )}
        </div>
      ))}
      <datalist id="tipos-operacion-of">
        {['CORTE', 'PLEGADO', 'SOLDADURA', 'MONTAJE', 'MONTAJE_ELECTRICO', 'PINTURA', 'PRUEBA', 'EMBALAJE', 'RETRABAJO', 'MECANIZADO'].map((t) => (
          <option key={t} value={t} />
        ))}
      </datalist>
      <button onClick={() => setOps([...ops, { tipo: '', minutos: '', maquina: '', seccion: ops[ops.length - 1]?.seccion ?? '' }])}>+ otra operación</button>
      <div className="botones" style={{ marginTop: 8 }}>
        <label>
          <input type="checkbox" checked={f.urgente} onChange={(e) => setF({ ...f, urgente: e.target.checked })} /> Urgente
        </label>
      </div>
      <MensajeError error={err} />
      <div className="botones" style={{ marginTop: 8 }}>
        <button
          className="primario"
          disabled={!valido}
          onClick={async () => {
            try {
              const semana = f.semana ? f.semana.replace('-W', '') : null
              const r = await api.post<{ id: number; numero: string }>('/ofs', {
                numero: f.numero || null,
                descripcion: f.descripcion || null,
                tanda_id: f.tanda_id ? Number(f.tanda_id) : null,
                semana,
                urgente: f.urgente,
                operaciones: ops.map((o) => ({ tipo: o.tipo, minutos: Number(o.minutos), maquina: o.maquina || null, seccion: o.seccion || null })),
              })
              onHecho(r)
            } catch (e) {
              setErr(e)
            }
          }}
        >
          Crear OF
        </button>
        <button onClick={onCerrar}>Cancelar</button>
      </div>
    </Modal>
  )
}
