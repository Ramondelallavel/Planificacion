import { useState } from 'react'
import { Link } from 'react-router-dom'
import { api, puede } from '../api'
import { useSesion } from '../App'
import { Cargando, Kpi, MensajeError, Modal, useDatos } from '../componentes/comunes'
import { fecha, isoLocal } from '../formato'
import { aCsv, descargar } from '../plataforma'

interface FilaMaterial {
  codigo: string
  descripcion: string | null
  unidad: string | null
  controlado: boolean
  registrado: boolean
  stock: number | null
  plazo_dias: number | null
  necesidad: number
  ofs: number
  entradas: { id: number; cantidad: number; fecha: string; referencia: string | null }[]
  balance: number | null
  ofs_falta: number
  ofs_esperan: number
  notas: string | null
}
interface DatosMateriales {
  materiales: FilaMaterial[]
  resumen: { controlados: number; necesarios: number; con_falta: number; ofs_bloqueadas: number; ofs_esperan: number }
}
interface Consumidor {
  of: string
  of_id: number
  cantidad: number
  estado: string
  fecha: string | null
  inicio_plan: string | null
}

const n = (x: number | null | undefined) => (x == null ? '—' : x.toLocaleString('es-ES', { maximumFractionDigits: 2 }))
const ESTADO: Record<string, [string, string]> = {
  CUBIERTA: ['VERDE', 'cubierta por stock'],
  CON_ENTRADA: ['AMARILLO', 'espera una entrada'],
  REPOSICION: ['AMARILLO', 'espera reposición'],
  FALTA: ['ROJO', 'sin material'],
  SIN_CONTROL: ['', 'sin controlar'],
}

/** Stock y entradas previstas frente a lo que consumen las OF abiertas. */
export default function Materiales() {
  const { sesion } = useSesion()
  const { datos, error, recargar } = useDatos(() => api.get<DatosMateriales>('/materiales'), [])
  const [filtro, setFiltro] = useState<'todos' | 'controlados' | 'falta'>('todos')
  const [texto, setTexto] = useState('')
  const [editar, setEditar] = useState<FilaMaterial | 'nuevo' | null>(null)
  const [entrada, setEntrada] = useState<FilaMaterial | null>(null)
  const [detalle, setDetalle] = useState<string | null>(null)
  const [msg, setMsg] = useState<string | null>(null)
  const [pendiente, setPendiente] = useState(false)
  const [ocupado, setOcupado] = useState(false)
  const [err, setErr] = useState<unknown>(null)
  const gestionar = puede(sesion, 'recursos')
  const planificar = puede(sesion, 'planificar')
  if (error) return <MensajeError error={error} />
  if (!datos) return <Cargando />

  const t = texto.trim().toLowerCase()
  const filas = datos.materiales.filter(
    (m) =>
      (filtro === 'todos' || (filtro === 'controlados' ? m.controlado : m.ofs_falta > 0 || (m.balance ?? 0) < 0)) &&
      (!t || m.codigo.toLowerCase().includes(t) || (m.descripcion ?? '').toLowerCase().includes(t)),
  )
  const cambiado = (texto: string) => {
    setEditar(null)
    setEntrada(null)
    setMsg(texto)
    setPendiente(true)
    recargar()
  }
  const calcular = async () => {
    setOcupado(true)
    setErr(null)
    try {
      const r = await api.post<{ con_material: number; con_fecha: number; bloqueadas: number; liberadas: number; no_planificadas?: number }>('/materiales/calcular?replanificar=true')
      setMsg(
        `Disponibilidad aplicada: ${r.con_material} OF con material, ${r.con_fecha} esperando una entrada, ${r.bloqueadas} bloqueadas por falta${r.liberadas ? `, ${r.liberadas} vuelven a «sin dato»` : ''}. Plan regenerado.`,
      )
      setPendiente(false)
      recargar()
    } catch (e) {
      setErr(e)
    } finally {
      setOcupado(false)
    }
  }
  const importar = async (f: File | undefined) => {
    if (!f) return
    setErr(null)
    try {
      const r = await api.subir<{ materiales: number; errores: string[] }>('/materiales/importar', f)
      cambiado(`Stock importado: ${r.materiales} materiales${r.errores.length ? ` · ${r.errores.length} filas con errores (${r.errores.slice(0, 2).join('; ')})` : ''}.`)
    } catch (e) {
      setErr(e)
    }
  }

  return (
    <>
      <div className="cabecera">
        <div>
          <h1>Materiales</h1>
          <div className="sub">
            Lo que consumen las OF abiertas (barras, tubos, perfiles y componentes de compra que vienen en los PDF) frente a stock y entradas previstas. Solo cuentan los materiales que
            controlas; al calcular, cada OF sabe desde cuándo tiene material y el plan lo respeta.
          </div>
        </div>
        <div className="botones">
          {gestionar && (
            <>
              <button onClick={() => setEditar('nuevo')}>+ Material</button>
              <label className="boton">
                Importar stock (CSV)
                <input type="file" accept=".csv,text/csv" style={{ display: 'none' }} onChange={(e) => importar(e.target.files?.[0])} />
              </label>
            </>
          )}
          <button
            onClick={() =>
              descargar(
                'materiales.csv',
                aCsv(datos.materiales as unknown as Record<string, unknown>[], [
                  ['codigo', 'codigo'],
                  ['descripcion', 'descripcion'],
                  ['unidad', 'unidad'],
                  ['stock', 'stock'],
                  ['necesidad', 'Necesidad OF abiertas'],
                  ['balance', 'Balance'],
                  ['ofs', 'OF'],
                ]),
                'text/csv',
              )
            }
          >
            Exportar CSV
          </button>
          {planificar && (
            <button className="primario" disabled={ocupado} onClick={calcular}>
              {ocupado ? 'Calculando…' : 'Aplicar al plan'}
            </button>
          )}
        </div>
      </div>
      {msg && <div className={`mensaje ${pendiente ? 'aviso' : 'ok'}`}>{msg}{pendiente && ' Pulsa «Aplicar al plan» para que el plan lo tenga en cuenta.'}</div>}
      <MensajeError error={err} />

      <div className="kpis">
        <Kpi valor={datos.resumen.necesarios} etiqueta="materiales que necesitan las OF abiertas" />
        <Kpi valor={datos.resumen.controlados} etiqueta="controlados (con stock registrado)" />
        <Kpi valor={datos.resumen.con_falta} etiqueta="con falta" nivel={datos.resumen.con_falta ? 'ROJO' : undefined} />
        <Kpi valor={datos.resumen.ofs_bloqueadas} etiqueta={`OF bloqueadas por material · ${datos.resumen.ofs_esperan} esperando entrada`} nivel={datos.resumen.ofs_bloqueadas ? 'NARANJA' : undefined} />
      </div>

      <section className="panel">
        <div className="filtros-gantt">
          <select value={filtro} onChange={(e) => setFiltro(e.target.value as typeof filtro)}>
            <option value="todos">Todos</option>
            <option value="controlados">Solo controlados</option>
            <option value="falta">Solo con falta</option>
          </select>
          <input placeholder="Buscar código o descripción…" value={texto} onChange={(e) => setTexto(e.target.value)} />
          <span className="pequeno tenue">{filas.length} materiales</span>
        </div>
        {datos.materiales.length === 0 ? (
          <p className="tenue">Las OF abiertas no traen consumos de material en sus PDF. Puedes dar de alta materiales a mano.</p>
        ) : (
          <div className="tabla-desplazable">
            <table>
              <thead>
                <tr>
                  <th>Material</th>
                  <th className="num">Necesitan las OF</th>
                  <th className="num">Stock</th>
                  <th>Entradas previstas</th>
                  <th className="num">Balance</th>
                  <th>OF</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {filas.map((m) => (
                  <tr key={m.codigo} className={m.controlado ? '' : 'tenue-suave'}>
                    <td>
                      <span className="mono">{m.codigo}</span> {!m.controlado && <span className="etiqueta">sin controlar</span>}
                      <div className="pequeno tenue">{m.descripcion}</div>
                    </td>
                    <td className="num">
                      {n(m.necesidad)} <span className="pequeno tenue">{m.unidad ?? ''}</span>
                    </td>
                    <td className="num">{m.controlado ? n(m.stock) : '—'}</td>
                    <td className="pequeno">
                      {m.entradas.map((e) => (
                        <div key={e.id} className="entrada-material">
                          {n(e.cantidad)} el {fecha(e.fecha).slice(0, 9)} {e.referencia && <span className="tenue">({e.referencia})</span>}
                          {gestionar && (
                            <>
                              {' '}
                              <button
                                className="enlace"
                                onClick={async () => {
                                  await api.post(`/materiales/entradas/${e.id}/recibir`)
                                  cambiado(`Recibidas ${n(e.cantidad)} de ${m.codigo}: pasan al stock.`)
                                }}
                              >
                                recibir
                              </button>{' '}
                              <button
                                className="enlace"
                                onClick={async () => {
                                  await api.del(`/materiales/entradas/${e.id}`)
                                  cambiado(`Entrada de ${m.codigo} anulada.`)
                                }}
                              >
                                anular
                              </button>
                            </>
                          )}
                        </div>
                      ))}
                      {m.plazo_dias != null && <div className="tenue">reposición en {m.plazo_dias} días</div>}
                    </td>
                    <td className="num">
                      {m.balance == null ? '—' : <span className={`riesgo ${m.balance < 0 ? 'ROJO' : 'VERDE'}`}>{n(m.balance)}</span>}
                      {(m.ofs_falta > 0 || m.ofs_esperan > 0) && (
                        <div className="pequeno">
                          {m.ofs_falta > 0 && <span className="riesgo ROJO">{m.ofs_falta} OF sin material</span>} {m.ofs_esperan > 0 && <span className="riesgo AMARILLO">{m.ofs_esperan} esperan</span>}
                        </div>
                      )}
                    </td>
                    <td>
                      <button className="enlace" onClick={() => setDetalle(m.codigo)}>
                        {m.ofs} OF
                      </button>
                    </td>
                    <td>
                      {gestionar && (
                        <div className="botones">
                          <button onClick={() => setEditar(m)}>{m.controlado ? 'Stock' : 'Controlar'}</button>
                          <button onClick={() => setEntrada(m)}>+ Entrada</button>
                        </div>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        <p className="pequeno tenue">
          Las cantidades son las del PDF (longitudes en mm en barras y perfiles, unidades en componentes). El CSV de stock lleva las columnas <span className="mono">codigo;descripcion;unidad;stock</span>.
        </p>
      </section>

      {editar && <EditarMaterial m={editar === 'nuevo' ? null : editar} onCerrar={() => setEditar(null)} onHecho={cambiado} />}
      {entrada && <NuevaEntrada m={entrada} onCerrar={() => setEntrada(null)} onHecho={cambiado} />}
      {detalle && <DetalleMaterial codigo={detalle} onCerrar={() => setDetalle(null)} />}
    </>
  )
}

function EditarMaterial({ m, onCerrar, onHecho }: { m: FilaMaterial | null; onCerrar: () => void; onHecho: (t: string) => void }) {
  const [f, setF] = useState({
    codigo: m?.codigo ?? '',
    descripcion: m?.descripcion ?? '',
    unidad: m?.unidad ?? 'ud',
    stock: m?.stock != null ? String(m.stock) : '0',
    plazo: m?.plazo_dias != null ? String(m.plazo_dias) : '',
    notas: m?.notas ?? '',
  })
  const [err, setErr] = useState<unknown>(null)
  return (
    <Modal titulo={m ? `Material ${m.codigo}` : 'Nuevo material'} onCerrar={onCerrar}>
      {m && !m.controlado && <p className="pequeno tenue">Al guardar empieza a controlarse: las OF que lo consumen solo tendrán material si hay stock o entradas que las cubran.</p>}
      <div className="formulario">
        <label className="campo">
          Código de artículo
          <input value={f.codigo} disabled={!!m} onChange={(e) => setF({ ...f, codigo: e.target.value })} />
        </label>
        <label className="campo">
          Descripción
          <input value={f.descripcion} onChange={(e) => setF({ ...f, descripcion: e.target.value })} />
        </label>
        <label className="campo">
          Unidad
          <input value={f.unidad} onChange={(e) => setF({ ...f, unidad: e.target.value })} placeholder="mm, m, kg, ud…" />
        </label>
        <label className="campo">
          Stock actual
          <input id="material-stock" type="number" min={0} step="any" value={f.stock} onChange={(e) => setF({ ...f, stock: e.target.value })} />
        </label>
        <label className="campo">
          Plazo de reposición (días, opcional)
          <input type="number" min={0} value={f.plazo} onChange={(e) => setF({ ...f, plazo: e.target.value })} placeholder="si falta y no hay pedido" />
        </label>
        <label className="campo">
          Notas
          <input value={f.notas} onChange={(e) => setF({ ...f, notas: e.target.value })} />
        </label>
      </div>
      <MensajeError error={err} />
      <div className="botones" style={{ marginTop: 8 }}>
        <button
          className="primario"
          disabled={!f.codigo}
          onClick={async () => {
            try {
              await api.post('/materiales', {
                codigo: f.codigo,
                descripcion: f.descripcion || null,
                unidad: f.unidad || null,
                stock: Number(f.stock) || 0,
                controlado: true,
                plazo_dias: f.plazo ? Number(f.plazo) : null,
                notas: f.notas || null,
              })
              onHecho(`Stock de ${f.codigo}: ${n(Number(f.stock) || 0)} ${f.unidad}.`)
            } catch (e) {
              setErr(e)
            }
          }}
        >
          Guardar
        </button>
        {m?.controlado && (
          <button
            onClick={async () => {
              try {
                await api.del(`/materiales?codigo=${encodeURIComponent(m.codigo)}`)
                onHecho(`${m.codigo} deja de controlarse.`)
              } catch (e) {
                setErr(e)
              }
            }}
          >
            Dejar de controlar
          </button>
        )}
        <button onClick={onCerrar}>Cancelar</button>
      </div>
    </Modal>
  )
}

function NuevaEntrada({ m, onCerrar, onHecho }: { m: FilaMaterial; onCerrar: () => void; onHecho: (t: string) => void }) {
  const manana = new Date()
  manana.setDate(manana.getDate() + 1)
  manana.setHours(8, 0, 0, 0)
  const [cantidad, setCantidad] = useState(m.balance != null && m.balance < 0 ? String(-m.balance) : '')
  const [fechaTxt, setFechaTxt] = useState(isoLocal(manana))
  const [referencia, setReferencia] = useState('')
  const [err, setErr] = useState<unknown>(null)
  return (
    <Modal titulo={`Entrada prevista de ${m.codigo}`} onCerrar={onCerrar}>
      <p className="pequeno tenue">{m.descripcion}</p>
      <div className="formulario">
        <label className="campo">
          Cantidad ({m.unidad ?? 'ud'})
          <input id="entrada-cantidad" type="number" min={0} step="any" value={cantidad} onChange={(e) => setCantidad(e.target.value)} />
        </label>
        <label className="campo">
          Llega
          <input type="datetime-local" value={fechaTxt} onChange={(e) => setFechaTxt(e.target.value)} />
        </label>
        <label className="campo">
          Pedido / proveedor
          <input value={referencia} onChange={(e) => setReferencia(e.target.value)} />
        </label>
      </div>
      <MensajeError error={err} />
      <div className="botones" style={{ marginTop: 8 }}>
        <button
          className="primario"
          disabled={!Number(cantidad) || !fechaTxt}
          onClick={async () => {
            try {
              await api.post('/materiales/entradas', { codigo: m.codigo, cantidad: Number(cantidad), fecha_prevista: fechaTxt, referencia: referencia || null })
              onHecho(`Entrada de ${n(Number(cantidad))} ${m.unidad ?? ''} de ${m.codigo} prevista el ${fecha(fechaTxt)}.`)
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

function DetalleMaterial({ codigo, onCerrar }: { codigo: string; onCerrar: () => void }) {
  const { datos } = useDatos(() => api.get<{ codigo: string; descripcion: string | null; consumidores: Consumidor[] }>(`/materiales/detalle?codigo=${encodeURIComponent(codigo)}`), [codigo])
  return (
    <Modal titulo={`Quién consume ${codigo}`} onCerrar={onCerrar}>
      {!datos ? (
        <Cargando />
      ) : (
        <>
          <p className="pequeno tenue">{datos.descripcion} · en orden de necesidad (inicio en el plan).</p>
          <table>
            <thead>
              <tr>
                <th>OF</th>
                <th className="num">Cantidad</th>
                <th>Empieza (plan)</th>
                <th>Material</th>
              </tr>
            </thead>
            <tbody>
              {datos.consumidores.map((c) => (
                <tr key={c.of_id}>
                  <td>
                    <Link to={`/ofs/${c.of_id}`} onClick={onCerrar}>
                      OF {c.of}
                    </Link>
                  </td>
                  <td className="num">{n(c.cantidad)}</td>
                  <td className="pequeno">{c.inicio_plan ? fecha(c.inicio_plan) : '—'}</td>
                  <td className="pequeno">
                    <span className={`riesgo ${ESTADO[c.estado]?.[0] ?? ''}`}>{ESTADO[c.estado]?.[1] ?? c.estado}</span>
                    {c.fecha && ` desde ${fecha(c.fecha)}`}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </>
      )}
    </Modal>
  )
}
