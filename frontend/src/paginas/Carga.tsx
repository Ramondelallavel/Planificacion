import { Fragment, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { api, puede } from '../api'
import { useSesion } from '../App'
import { Cargando, Kpi, MensajeError, Modal, useDatos } from '../componentes/comunes'
import { NuevaOF } from '../componentes/EditorOperaciones'
import { fecha } from '../formato'

interface Maquina {
  id: number
  codigo: string
  nombre: string
  unidades: number
  estado: string
  horas_disponibles: number
  horas_fijadas: number
  operaciones: string[]
}
interface Equipo {
  seccion: string
  nombre: string | null
  rendimiento: number
  demanda_h: number
  demanda_base_h: number
  operaciones: number
  sin_tiempo: number
  capacidad_maquinas_h: number
  capacidad_personas_h: number
  capacidad_h: number
  carga: number | null
  limitada_por: string
  maquinas: Maquina[]
  operarios: { id: number; codigo: string; nombre: string; turno: string | null; compartido: boolean }[]
  por_tanda: { tanda: string; horas: number }[]
  por_tipo: { tipo: string; horas: number }[]
}
interface DatosCarga {
  ahora: string
  hasta: string
  dias: number
  secciones: Equipo[]
}

const nivel = (c: number | null) => (c == null ? 'ROJO' : c >= 1 ? 'ROJO' : c >= 0.85 ? 'NARANJA' : c >= 0.6 ? 'AMARILLO' : 'VERDE')
const h = (x: number) => `${x.toLocaleString('es-ES', { maximumFractionDigits: 1 })} h`

/** Carga de cada equipo (sección) frente a su capacidad, y las palancas para cambiarla. */
export default function Carga() {
  const { sesion } = useSesion()
  const [dias, setDias] = useState(14)
  const { datos, error, recargar } = useDatos(() => api.get<DatosCarga>(`/carga?dias=${dias}`), [dias])
  const [abierta, setAbierta] = useState<string | null>(null)
  const [modal, setModal] = useState<{ tipo: 'mover' | 'operarios' | 'maquina' | 'of'; equipo?: Equipo } | null>(null)
  const [pendiente, setPendiente] = useState<string | null>(null)
  const [replan, setReplan] = useState<string | null>(null)
  const [ocupado, setOcupado] = useState(false)
  const navegar = useNavigate()
  const planificar = puede(sesion, 'planificar')
  const recursos = puede(sesion, 'recursos')
  if (error) return <MensajeError error={error} />
  if (!datos) return <Cargando />

  const hecho = (texto: string) => {
    setModal(null)
    setPendiente(texto)
    setReplan(null)
    recargar()
  }
  const replanificar = async () => {
    setOcupado(true)
    try {
      const r = await api.post<{ kpis: { planificadas: number; no_planificadas: number; cumplimiento_semana: number | null } }>('/plan/generar', { motivo: pendiente ?? 'Cambios de carga y capacidad' })
      setReplan(
        `Plan regenerado: ${r.kpis.planificadas} operaciones planificadas${r.kpis.no_planificadas ? `, ${r.kpis.no_planificadas} no planificables` : ''}${r.kpis.cumplimiento_semana != null ? ` · cumplimiento de semana ${Math.round(r.kpis.cumplimiento_semana * 100)} %` : ''}.`,
      )
      setPendiente(null)
      recargar()
    } catch (e) {
      setReplan(e instanceof Error ? e.message : String(e))
    } finally {
      setOcupado(false)
    }
  }
  const total = datos.secciones.reduce((a, s) => ({ d: a.d + s.demanda_h, c: a.c + s.capacidad_h }), { d: 0, c: 0 })

  return (
    <>
      <div className="cabecera">
        <div>
          <h1>Carga de trabajo</h1>
          <div className="sub">
            Horas pendientes de cada equipo frente a lo que pueden hacer sus máquinas y su gente hasta el {fecha(datos.hasta)}. Cambia tiempos, rendimiento, reparte carga o añade
            recursos, y replanifica para ver el efecto.
          </div>
        </div>
        <div className="botones">
          <select id="carga-dias" value={dias} onChange={(e) => setDias(Number(e.target.value))}>
            <option value={7}>7 días</option>
            <option value={14}>14 días</option>
            <option value={21}>21 días</option>
          </select>
          {puede(sesion, 'modificar_plan') && <button onClick={() => setModal({ tipo: 'of' })}>+ Nueva OF</button>}
          {planificar && (
            <button className="primario" disabled={ocupado} onClick={replanificar}>
              {ocupado ? 'Replanificando…' : 'Replanificar'}
            </button>
          )}
        </div>
      </div>
      {pendiente && (
        <div className="mensaje aviso">
          {pendiente} El plan cambia al replanificar.{' '}
          {planificar && (
            <button className="enlace" onClick={replanificar} disabled={ocupado}>
              Replanificar ahora
            </button>
          )}
        </div>
      )}
      {replan && <div className="mensaje ok">{replan}</div>}

      <div className="kpis">
        <Kpi valor={h(total.d)} etiqueta="de trabajo pendiente en el plan" />
        <Kpi valor={h(total.c)} etiqueta={`de capacidad en ${datos.dias} días`} />
        <Kpi valor={total.c ? `${Math.round((100 * total.d) / total.c)} %` : '—'} etiqueta="carga global" nivel={nivel(total.c ? total.d / total.c : null)} />
      </div>

      <section className="panel">
        <table className="tabla-carga">
          <thead>
            <tr>
              <th>Equipo</th>
              <th className="num">Pendiente</th>
              <th className="num">Capacidad</th>
              <th style={{ width: '22%' }}>Carga</th>
              <th className="num">Rendimiento</th>
              <th className="num">Gente</th>
              <th className="num">Máquinas</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {[...datos.secciones]
              .sort((a, b) => (b.demanda_h > 0 ? 1 : 0) - (a.demanda_h > 0 ? 1 : 0) || (b.carga ?? 9) - (a.carga ?? 9) || a.seccion.localeCompare(b.seccion))
              .map((e) => (
              <Fragment key={e.seccion}>
                <tr className={abierta === e.seccion ? 'fila-elegida' : ''}>
                  <td>
                    <button className="enlace" onClick={() => setAbierta(abierta === e.seccion ? null : e.seccion)} aria-expanded={abierta === e.seccion}>
                      <strong>{e.seccion}</strong>
                    </button>{' '}
                    <span className="pequeno tenue">{e.nombre}</span>
                    {e.sin_tiempo > 0 && <div className="pequeno riesgo AMARILLO">{e.sin_tiempo} operaciones sin tiempo</div>}
                  </td>
                  <td className="num">
                    {h(e.demanda_h)}
                    <div className="pequeno tenue">{e.operaciones} op.</div>
                  </td>
                  <td className="num">
                    {h(e.capacidad_h)}
                    <div className="pequeno tenue" title="Máquinas / personas">
                      {h(e.capacidad_maquinas_h)} máq. · {h(e.capacidad_personas_h)} pers.
                    </div>
                  </td>
                  <td>
                    <div className={`barra-carga ${nivel(e.carga)}`} title={e.carga == null ? 'Sin capacidad en el periodo' : `${Math.round(e.carga * 100)} %`}>
                      <div style={{ width: `${Math.min(100, (e.carga ?? 1) * 100)}%` }} />
                      <span>{e.carga == null ? (e.demanda_h ? 'sin capacidad' : '—') : `${Math.round(e.carga * 100)} %`}</span>
                    </div>
                    {e.carga != null && e.demanda_h > 0 && <div className="pequeno tenue">limitada por {e.limitada_por}</div>}
                  </td>
                  <td className="num">
                    <Rendimiento equipo={e} editable={planificar} onHecho={(t) => hecho(t)} />
                  </td>
                  <td className="num">{e.operarios.length}</td>
                  <td className="num">{e.maquinas.reduce((n, m) => n + m.unidades, 0)}</td>
                  <td>
                    <div className="botones">
                      {planificar && e.demanda_h > 0 && <button onClick={() => setModal({ tipo: 'mover', equipo: e })}>Mover carga</button>}
                      {recursos && <button onClick={() => setModal({ tipo: 'operarios', equipo: e })}>+ Gente</button>}
                      {recursos && e.maquinas.length > 0 && <button onClick={() => setModal({ tipo: 'maquina', equipo: e })}>+ Máquina</button>}
                    </div>
                  </td>
                </tr>
                {abierta === e.seccion && (
                  <tr className="detalle-equipo">
                    <td colSpan={8}>
                      <div className="rejilla tres">
                        <div>
                          <h3>Máquinas</h3>
                          <table>
                            <tbody>
                              {e.maquinas.map((m) => (
                                <tr key={m.id}>
                                  <td>
                                    <Link to={`/gantt?buscar=${encodeURIComponent(m.codigo)}`}>{m.codigo}</Link> {m.unidades > 1 && <span className="etiqueta">×{m.unidades}</span>}{' '}
                                    {m.estado !== 'OPERATIVO' && <span className="riesgo ROJO">{m.estado}</span>}
                                    <div className="pequeno tenue">{m.nombre}</div>
                                  </td>
                                  <td className="num pequeno">
                                    {h(m.horas_disponibles)} disp.
                                    {m.horas_fijadas > 0 && <div className="tenue">{h(m.horas_fijadas)} fijadas a ella</div>}
                                  </td>
                                </tr>
                              ))}
                            </tbody>
                          </table>
                        </div>
                        <div>
                          <h3>Personas</h3>
                          {e.operarios.length === 0 ? (
                            <p className="pequeno riesgo ROJO">Nadie cualificado: sus operaciones no se pueden planificar.</p>
                          ) : (
                            <ul className="lista-plana pequeno">
                              {e.operarios.map((o) => (
                                <li key={o.id}>
                                  <Link to={`/operario?operario=${o.id}`}>{o.nombre}</Link> <span className="tenue">turno {o.turno ?? '—'}</span>
                                  {o.compartido && <span className="etiqueta">también en otros equipos</span>}
                                </li>
                              ))}
                            </ul>
                          )}
                        </div>
                        <div>
                          <h3>Qué trabajo tiene</h3>
                          <ul className="lista-plana pequeno">
                            {e.por_tanda.map((t) => (
                              <li key={t.tanda}>
                                Tanda {t.tanda}: {h(t.horas)}
                              </li>
                            ))}
                          </ul>
                          <ul className="lista-plana pequeno tenue">
                            {e.por_tipo.map((t) => (
                              <li key={t.tipo}>
                                {t.tipo}: {h(t.horas)}
                              </li>
                            ))}
                          </ul>
                          {e.rendimiento !== 100 && (
                            <p className="pequeno tenue">
                              Con tiempos estándar serían {h(e.demanda_base_h)}; al {e.rendimiento} % de rendimiento quedan {h(e.demanda_h)}.
                            </p>
                          )}
                        </div>
                      </div>
                    </td>
                  </tr>
                )}
              </Fragment>
            ))}
          </tbody>
        </table>
        <p className="pequeno tenue">
          La capacidad cuenta turnos, jornadas extra, festivos, paradas y ausencias. Si un equipo pasa del 100 %, lo que no cabe se va más allá del periodo: mira el riesgo en el{' '}
          <Link to="/">Control Tower</Link> y el reparto día a día en <Link to="/capacidad">Capacidad</Link>. Para cambiar el tiempo de una operación concreta, ábrela desde su OF.
        </p>
      </section>

      {modal?.tipo === 'mover' && modal.equipo && <MoverCarga equipo={modal.equipo} todos={datos.secciones} onCerrar={() => setModal(null)} onHecho={hecho} />}
      {modal?.tipo === 'operarios' && modal.equipo && <AnadirGente equipo={modal.equipo} onCerrar={() => setModal(null)} onHecho={hecho} />}
      {modal?.tipo === 'maquina' && modal.equipo && <AnadirMaquina equipo={modal.equipo} onCerrar={() => setModal(null)} onHecho={hecho} />}
      {modal?.tipo === 'of' && <NuevaOF onCerrar={() => setModal(null)} onHecho={(of) => navegar(`/ofs/${of.id}`)} />}
    </>
  )
}

function Rendimiento({ equipo, editable, onHecho }: { equipo: Equipo; editable: boolean; onHecho: (t: string) => void }) {
  const [v, setV] = useState(String(equipo.rendimiento))
  const [err, setErr] = useState<string | null>(null)
  if (!editable) return <>{equipo.rendimiento} %</>
  const guardar = async () => {
    const n = Number(v)
    if (!n || n === equipo.rendimiento) return
    try {
      await api.put('/carga/rendimiento', { seccion: equipo.seccion, rendimiento: n })
      setErr(null)
      onHecho(`Rendimiento de ${equipo.seccion} al ${n} %.`)
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e))
      setV(String(equipo.rendimiento))
    }
  }
  return (
    <span className="rendimiento" title="100 % = tiempos estándar. 120 % = el equipo hace el trabajo en menos tiempo; 80 % = necesita más.">
      <input
        aria-label={`Rendimiento de ${equipo.seccion}`}
        type="number"
        min={20}
        max={300}
        step={5}
        value={v}
        onChange={(e) => setV(e.target.value)}
        onBlur={guardar}
        onKeyDown={(e) => e.key === 'Enter' && guardar()}
      />{' '}
      %{err && <div className="pequeno riesgo ROJO">{err}</div>}
    </span>
  )
}

function MoverCarga({ equipo, todos, onCerrar, onHecho }: { equipo: Equipo; todos: Equipo[]; onCerrar: () => void; onHecho: (t: string) => void }) {
  const tandas = useDatos(() => api.get<{ id: number; numero: string; estado: string }[]>('/tandas'), [])
  const [desde, setDesde] = useState('')
  const [tipo, setTipo] = useState('')
  const [tanda, setTanda] = useState('')
  const [hacia, setHacia] = useState('')
  const [fijar, setFijar] = useState(true)
  const [motivo, setMotivo] = useState('')
  const [previa, setPrevia] = useState<{ operaciones: number; horas: number; ofs: number; n_rechazadas: number; rechazadas: string[] } | null>(null)
  const [err, setErr] = useState<unknown>(null)
  const destinos = todos.flatMap((e) => [
    { valor: `S:${e.seccion}`, texto: `Equipo ${e.seccion} (cualquier máquina)` },
    ...e.maquinas.map((m) => ({ valor: `M:${m.codigo}`, texto: `  ${m.codigo} · ${m.nombre} (${e.seccion})` })),
  ])
  const cuerpo = () => {
    const c: Record<string, unknown> = { tipo: tipo || null, tanda_id: tanda ? Number(tanda) : null, motivo: motivo || null }
    if (desde) c.desde_maquina = desde
    else c.desde_seccion = equipo.seccion
    if (hacia.startsWith('M:')) {
      c.hacia_maquina = hacia.slice(2)
      c.fijar_maquina = fijar
    } else c.hacia_seccion = hacia.slice(2)
    return c
  }
  const probar = async () => {
    setErr(null)
    try {
      setPrevia(await api.post('/carga/mover?aplicar=false', cuerpo()))
    } catch (e) {
      setErr(e)
    }
  }
  return (
    <Modal titulo={`Mover carga de ${equipo.seccion}`} onCerrar={onCerrar}>
      <p className="pequeno tenue">Pasa operaciones pendientes (no empezadas) a otra máquina o a otro equipo. Solo se mueven las que la máquina de destino sabe hacer.</p>
      <div className="formulario">
        <label className="campo">
          Desde
          <select id="mover-desde" value={desde} onChange={(e) => (setDesde(e.target.value), setPrevia(null))}>
            <option value="">todo el equipo {equipo.seccion}</option>
            {equipo.maquinas.map((m) => (
              <option key={m.id} value={m.codigo}>
                la máquina {m.codigo}
              </option>
            ))}
          </select>
        </label>
        <label className="campo">
          Solo operaciones de tipo
          <select value={tipo} onChange={(e) => (setTipo(e.target.value), setPrevia(null))}>
            <option value="">todas</option>
            {equipo.por_tipo.map((t) => (
              <option key={t.tipo} value={t.tipo}>
                {t.tipo} ({h(t.horas)})
              </option>
            ))}
          </select>
        </label>
        <label className="campo">
          Solo de la tanda
          <select value={tanda} onChange={(e) => (setTanda(e.target.value), setPrevia(null))}>
            <option value="">todas</option>
            {(tandas.datos ?? [])
              .filter((t) => t.estado === 'ACTIVA')
              .map((t) => (
                <option key={t.id} value={t.id}>
                  {t.numero}
                </option>
              ))}
          </select>
        </label>
        <label className="campo">
          Hacia
          <select id="mover-hacia" value={hacia} onChange={(e) => (setHacia(e.target.value), setPrevia(null))}>
            <option value="">elige destino…</option>
            {destinos
              .filter((d) => d.valor !== `S:${equipo.seccion}` && d.valor !== `M:${desde}`)
              .map((d) => (
                <option key={d.valor} value={d.valor}>
                  {d.texto}
                </option>
              ))}
          </select>
        </label>
        <label className="campo">
          Motivo
          <input value={motivo} onChange={(e) => setMotivo(e.target.value)} placeholder="equilibrar, máquina saturada…" />
        </label>
      </div>
      {hacia.startsWith('M:') && (
        <label className="pequeno">
          <input type="checkbox" checked={fijar} onChange={(e) => setFijar(e.target.checked)} /> Fijarlas a esa máquina (si no, el motor elige cualquiera de su equipo)
        </label>
      )}
      {previa && (
        <div className={`mensaje ${previa.operaciones ? 'ok' : 'aviso'}`}>
          Se moverían <strong>{previa.operaciones}</strong> operaciones de {previa.ofs} OF ({h(previa.horas)}).
          {previa.n_rechazadas > 0 && ` ${previa.n_rechazadas} no, porque el destino no hace ese tipo de operación (p.ej. ${previa.rechazadas.slice(0, 3).join(', ')}).`}
        </div>
      )}
      <MensajeError error={err} />
      <div className="botones" style={{ marginTop: 8 }}>
        <button disabled={!hacia} onClick={probar}>
          Ver cuánto se mueve
        </button>
        <button
          className="primario"
          disabled={!previa?.operaciones}
          onClick={async () => {
            try {
              const r = await api.post<{ operaciones: number; horas: number; hacia: string }>('/carga/mover', cuerpo())
              onHecho(`${r.operaciones} operaciones (${h(r.horas)}) movidas a ${r.hacia}.`)
            } catch (e) {
              setErr(e)
            }
          }}
        >
          Mover
        </button>
        <button onClick={onCerrar}>Cancelar</button>
      </div>
    </Modal>
  )
}

function AnadirGente({ equipo, onCerrar, onHecho }: { equipo: Equipo; onCerrar: () => void; onHecho: (t: string) => void }) {
  const turnos = useDatos(() => api.get<{ codigo: string; nombre: string; activo: boolean }[]>('/turnos'), [])
  const [cantidad, setCantidad] = useState('1')
  const [copiar, setCopiar] = useState(equipo.operarios[0] ? String(equipo.operarios[0].id) : '')
  const [turno, setTurno] = useState('')
  const [nombre, setNombre] = useState(`Refuerzo ${equipo.seccion}`)
  const [err, setErr] = useState<unknown>(null)
  return (
    <Modal titulo={`Añadir gente a ${equipo.seccion}`} onCerrar={onCerrar}>
      <p className="pequeno tenue">Da de alta operarios nuevos (refuerzos, ETT, traslados). Luego puedes cambiar su nombre y cualificaciones en Configuración → Operarios.</p>
      <div className="formulario">
        <label className="campo">
          Cuántos
          <input id="gente-cantidad" type="number" min={1} max={50} value={cantidad} onChange={(e) => setCantidad(e.target.value)} />
        </label>
        <label className="campo">
          Saben hacer lo mismo que
          <select value={copiar} onChange={(e) => setCopiar(e.target.value)}>
            <option value="">todas las máquinas de {equipo.seccion}</option>
            {equipo.operarios.map((o) => (
              <option key={o.id} value={o.id}>
                {o.nombre}
              </option>
            ))}
          </select>
        </label>
        <label className="campo">
          Turno
          <select value={turno} onChange={(e) => setTurno(e.target.value)}>
            <option value="">{copiar ? 'el mismo' : 'elige…'}</option>
            {(turnos.datos ?? [])
              .filter((t) => t.activo)
              .map((t) => (
                <option key={t.codigo} value={t.codigo}>
                  {t.codigo} · {t.nombre}
                </option>
              ))}
          </select>
        </label>
        <label className="campo">
          Nombre
          <input value={nombre} onChange={(e) => setNombre(e.target.value)} />
        </label>
      </div>
      <MensajeError error={err} />
      <div className="botones" style={{ marginTop: 8 }}>
        <button
          className="primario"
          disabled={!Number(cantidad) || (!copiar && !turno)}
          onClick={async () => {
            try {
              const r = await api.post<{ creados: string[] }>('/operarios/lote', {
                cantidad: Number(cantidad),
                copiar_de: copiar ? Number(copiar) : null,
                seccion: copiar ? null : equipo.seccion,
                turno: turno || null,
                nombre,
              })
              onHecho(`${r.creados.length} ${r.creados.length === 1 ? 'persona nueva' : 'personas nuevas'} en ${equipo.seccion} (${r.creados.join(', ')}).`)
            } catch (e) {
              setErr(e)
            }
          }}
        >
          Dar de alta
        </button>
        <button onClick={onCerrar}>Cancelar</button>
      </div>
    </Modal>
  )
}

function AnadirMaquina({ equipo, onCerrar, onHecho }: { equipo: Equipo; onCerrar: () => void; onHecho: (t: string) => void }) {
  const [base, setBase] = useState(String(equipo.maquinas[0]?.id ?? ''))
  const [cantidad, setCantidad] = useState('1')
  const [cualif, setCualif] = useState(true)
  const [err, setErr] = useState<unknown>(null)
  return (
    <Modal titulo={`Añadir máquinas a ${equipo.seccion}`} onCerrar={onCerrar}>
      <p className="pequeno tenue">Crea máquinas iguales a una existente (mismas operaciones y turnos). Para una máquina distinta, usa Configuración → Recursos.</p>
      <div className="formulario">
        <label className="campo">
          Igual que
          <select value={base} onChange={(e) => setBase(e.target.value)}>
            {equipo.maquinas.map((m) => (
              <option key={m.id} value={m.id}>
                {m.codigo} · {m.nombre}
              </option>
            ))}
          </select>
        </label>
        <label className="campo">
          Cuántas
          <input id="maquina-cantidad" type="number" min={1} max={20} value={cantidad} onChange={(e) => setCantidad(e.target.value)} />
        </label>
      </div>
      <label className="pequeno">
        <input type="checkbox" checked={cualif} onChange={(e) => setCualif(e.target.checked)} /> Quien sabe usar la original sabe usar las nuevas
      </label>
      <MensajeError error={err} />
      <div className="botones" style={{ marginTop: 8 }}>
        <button
          className="primario"
          disabled={!base || !Number(cantidad)}
          onClick={async () => {
            try {
              const r = await api.post<{ nuevos: string[] }>(`/recursos/${base}/duplicar`, { cantidad: Number(cantidad), copiar_cualificaciones: cualif })
              onHecho(`Máquinas nuevas en ${equipo.seccion}: ${r.nuevos.join(', ')}.`)
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
