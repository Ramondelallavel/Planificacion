import { useState } from 'react'
import { api, ErrorApi, puede } from '../api'
import { useSesion } from '../App'
import { Cargando, MensajeError, Modal, useDatos } from '../componentes/comunes'
import { duracion, fecha, hora } from '../formato'

interface Tarjeta {
  operacion_id: number
  of: string | null
  of_id: number
  aparato: string | null
  tanda: number | null
  operacion: string
  descripcion: string | null
  maquina: string | null
  maquina_nombre: string | null
  cantidad: number | null
  cantidad_hecha: number | null
  tiempo_estimado_min: number | null
  inicio_previsto: string | null
  fin_previsto: string | null
  provisional: boolean
  puede_iniciar: boolean
  bloqueos: string[]
  programa: string | null
  fichaje_id?: number
  estado_fichaje?: 'ABIERTO' | 'PAUSADO'
  fichaje_inicio?: string
}

interface Trabajo {
  operario: { id: number; codigo: string; nombre: string; turno: string | null }
  actual: Tarjeta | null
  siguiente: Tarjeta | null
  despues: Tarjeta[]
  avisos: { id: number; titulo: string; mensaje: string; fecha: string; nivel: string }[]
}

const TIPOS_INCIDENCIA: [string, string][] = [
  ['AVERIA', 'Avería de la máquina'],
  ['FALTA_MATERIAL', 'Falta material'],
  ['CALIDAD', 'Problema de calidad'],
  ['OTRA', 'Otra'],
]

/** Pantalla de operario: lo mínimo, grande y claro. */
export default function Operario() {
  const { sesion } = useSesion()
  const supervisa = puede(sesion, 'fichar_supervisado')
  const [elegido, setElegido] = useState<number | null>(sesion?.operario_id ?? null)
  const operarios = useDatos(() => (supervisa ? api.get<{ id: number; codigo: string; nombre: string; turno: string | null }[]>('/operarios') : Promise.resolve([])), [supervisa])
  const oid = elegido ?? sesion?.operario_id ?? null
  const trabajo = useDatos(() => (oid ? api.get<Trabajo>(`/operario/trabajo${oid !== sesion?.operario_id ? `?operario_id=${oid}` : ''}`) : Promise.resolve(null)), [oid], 30000)
  const [err, setErr] = useState<unknown>(null)
  const [ok, setOk] = useState<string | null>(null)
  const [dialogo, setDialogo] = useState<null | 'pausar' | 'terminar' | 'incidencia'>(null)
  const [ocupado, setOcupado] = useState(false)

  const accion = async (f: () => Promise<string | null>) => {
    setErr(null)
    setOk(null)
    setOcupado(true)
    try {
      setOk(await f())
      setDialogo(null)
      trabajo.recargar()
    } catch (e) {
      setErr(e)
    } finally {
      setOcupado(false)
    }
  }

  const cuerpoOperario = oid !== sesion?.operario_id ? { operario_id: oid } : {}

  const iniciar = (t: Tarjeta, autorizar = false) =>
    accion(async () => {
      await api.post('/operario/iniciar', { operacion_id: t.operacion_id, ...cuerpoOperario, autorizado_por: autorizar ? sesion?.usuario : null })
      return `Iniciado: OF ${t.of} · ${t.operacion}`
    })

  if (!oid) {
    return (
      <div className="operario">
        <h1>Pantalla de operario</h1>
        {supervisa ? (
          <SelectorOperario operarios={operarios.datos ?? []} valor={null} onCambio={setElegido} />
        ) : (
          <div className="mensaje aviso">Tu usuario no está vinculado a ningún operario. Pide al administrador que lo vincule.</div>
        )}
      </div>
    )
  }

  const d = trabajo.datos
  const actual = d?.actual ?? null
  const proxima = d?.siguiente ?? null
  // lo que se muestra en grande: el trabajo abierto o, si no hay, el siguiente previsto
  const t = actual ?? proxima
  // bloqueos "blandos" (predecesora sin terminar, antes de hora…): un supervisor puede autorizar
  const errorFichaje = err instanceof ErrorApi && err.estado === 409 && !actual && err.errores.some((e) => e.includes('autorizar'))

  return (
    <div className="operario">
      <div className="cabecera">
        <div>
          <h1>{d ? d.operario.nombre : 'Operario'}</h1>
          <div className="sub">{d && `${d.operario.codigo} · turno ${d.operario.turno ?? '—'}`}</div>
        </div>
        {supervisa && <SelectorOperario operarios={operarios.datos ?? []} valor={oid} onCambio={setElegido} />}
      </div>

      {d?.avisos.map((a) => (
        <div key={a.id} className={`mensaje ${a.nivel === 'ALERTA' ? 'error' : 'aviso'}`} style={{ fontSize: 17 }}>
          <strong>{a.titulo}</strong> <span className="pequeno tenue">{fecha(a.fecha)}</span>
          <div style={{ whiteSpace: 'pre-line' }}>{a.mensaje}</div>
          <button
            style={{ marginTop: 6 }}
            onClick={async () => {
              await api.post(`/notificaciones/${a.id}/leida`)
              trabajo.recargar()
            }}
          >
            Entendido
          </button>
        </div>
      ))}

      {ok && (
        <div className="mensaje ok" style={{ fontSize: 18 }}>
          {ok}
        </div>
      )}
      <MensajeError error={err} />
      {errorFichaje && supervisa && t && (
        <button onClick={() => iniciar(t, true)} disabled={ocupado} style={{ marginBottom: 10 }}>
          Autorizar inicio igualmente (queda registrado a tu nombre)
        </button>
      )}

      {!d ? (
        trabajo.error ? <MensajeError error={trabajo.error} /> : <Cargando />
      ) : !t ? (
        <div className="trabajo-actual">
          <div className="titulo">TU TRABAJO ACTUAL</div>
          <p style={{ fontSize: 20 }}>No tienes trabajo asignado en el plan. Consulta con tu jefe de equipo.</p>
        </div>
      ) : (
        <div className="trabajo-actual">
          <div className="titulo">
            {actual ? (actual.estado_fichaje === 'PAUSADO' ? 'TU TRABAJO ACTUAL · EN PAUSA' : 'TU TRABAJO ACTUAL · EN MARCHA') : 'TU SIGUIENTE TRABAJO'}
          </div>
          <dl>
            <dt>OF</dt>
            <dd>{t.of ?? 'DATO NO DISPONIBLE'}</dd>
            <dt>Aparato</dt>
            <dd>{t.aparato ?? 'DATO NO DISPONIBLE'}</dd>
            <dt>Operación</dt>
            <dd>
              {t.operacion}
              {/* la descripción lleva entre paréntesis cómo se derivó la operación: al operario no le aporta */}
              {t.descripcion && <div style={{ fontSize: 15, fontWeight: 500 }}>{t.descripcion.replace(/\s*\([^)]*\)$/, '')}</div>}
            </dd>
            <dt>Máquina</dt>
            <dd>
              {t.maquina ?? 'DATO NO DISPONIBLE'} {t.maquina_nombre && <span style={{ fontSize: 15, fontWeight: 500 }}>{t.maquina_nombre}</span>}
            </dd>
            {t.programa && (
              <>
                <dt>Programa</dt>
                <dd className="mono" style={{ fontSize: 'inherit' }}>{t.programa}</dd>
              </>
            )}
            <dt>Cantidad</dt>
            <dd>
              {t.cantidad ?? 'DATO NO DISPONIBLE'}
              {!!t.cantidad_hecha && <span style={{ fontSize: 15, fontWeight: 500 }}> (hechas {t.cantidad_hecha})</span>}
            </dd>
            <dt>Tiempo estimado</dt>
            <dd>{duracion(t.tiempo_estimado_min)}</dd>
            {actual?.fichaje_inicio ? (
              <>
                <dt>Empezado</dt>
                <dd>{hora(actual.fichaje_inicio)}</dd>
              </>
            ) : (
              t.inicio_previsto && (
                <>
                  <dt>Previsto</dt>
                  <dd>
                    {fecha(t.inicio_previsto)} – {hora(t.fin_previsto)}
                  </dd>
                </>
              )
            )}
          </dl>
          {t.provisional && <div className="mensaje aviso">Provisional: la operación aún está pendiente de programación.</div>}
          {!actual && t.bloqueos.length > 0 && (
            <div className="mensaje error" style={{ fontSize: 17 }}>
              <strong>Todavía no se puede empezar:</strong>
              <ul>
                {t.bloqueos.map((b, i) => (
                  <li key={i}>{b}</li>
                ))}
              </ul>
            </div>
          )}
          <div className="botones-grandes">
            {!actual && (
              <button className="btn-iniciar" disabled={ocupado} onClick={() => iniciar(t)}>
                ▶ INICIAR
              </button>
            )}
            {actual && actual.estado_fichaje === 'ABIERTO' && (
              <button className="btn-pausar" disabled={ocupado} onClick={() => setDialogo('pausar')}>
                ❚❚ PAUSAR
              </button>
            )}
            {actual && actual.estado_fichaje === 'PAUSADO' && (
              <button
                className="btn-iniciar"
                disabled={ocupado}
                onClick={() =>
                  accion(async () => {
                    await api.post(`/operario/fichajes/${actual.fichaje_id}/reanudar`)
                    return 'Trabajo reanudado'
                  })
                }
              >
                ▶ REANUDAR
              </button>
            )}
            {actual && (
              <button className="btn-terminar" disabled={ocupado} onClick={() => setDialogo('terminar')}>
                ✔ TERMINAR
              </button>
            )}
            <button className="btn-incidencia" disabled={ocupado} onClick={() => setDialogo('incidencia')}>
              ⚠ INCIDENCIA
            </button>
          </div>
        </div>
      )}

      {d && (actual ? [proxima, ...d.despues] : d.despues).filter(Boolean).length > 0 && (
        <section className="panel" style={{ marginTop: 16 }}>
          <h2>Después</h2>
          <ul className="lista-plana">
            {(actual ? [proxima, ...d.despues] : d.despues)
              .filter((x): x is Tarjeta => !!x)
              .map((x) => (
                <li key={x.operacion_id} style={{ fontSize: 16 }}>
                  <strong>{hora(x.inicio_previsto)}</strong> · OF {x.of} · {x.operacion} · {x.maquina} · {x.cantidad ?? '—'} uds
                  {x.bloqueos.length > 0 && <div className="pequeno tenue">{x.bloqueos[0]}</div>}
                </li>
              ))}
          </ul>
        </section>
      )}

      {dialogo === 'pausar' && actual && (
        <DialogoPausa
          ocupado={ocupado}
          onCerrar={() => setDialogo(null)}
          onAceptar={(motivo) =>
            accion(async () => {
              await api.post(`/operario/fichajes/${actual.fichaje_id}/pausar`, { motivo })
              return 'Trabajo en pausa'
            })
          }
        />
      )}
      {dialogo === 'terminar' && actual && (
        <DialogoTerminar
          t={actual}
          ocupado={ocupado}
          onCerrar={() => setDialogo(null)}
          onAceptar={(cantidad, parcial) =>
            accion(async () => {
              const r = await api.post<{ estado: string; duracion_real_min: number; desviacion_min: number | null }>(`/operario/fichajes/${actual.fichaje_id}/terminar`, { cantidad, parcial })
              const desv = r.desviacion_min != null ? ` (${r.desviacion_min >= 0 ? '+' : ''}${Math.round(r.desviacion_min)} min respecto a lo previsto)` : ''
              return r.estado === 'TERMINADA' ? `Operación terminada en ${duracion(r.duracion_real_min)}${desv}` : `Registrado parcial: ${duracion(r.duracion_real_min)}. La operación sigue pendiente.`
            })
          }
        />
      )}
      {dialogo === 'incidencia' && (
        <DialogoIncidencia
          ocupado={ocupado}
          onCerrar={() => setDialogo(null)}
          onAceptar={(tipo, descripcion, horasEst) =>
            accion(async () => {
              const r = await api.post<{ replanificado?: boolean; resumen?: string }>('/operario/incidencia', {
                operacion_id: t?.operacion_id ?? null,
                tipo,
                descripcion,
                horas_estimadas: horasEst,
              })
              return `Incidencia registrada. Tu jefe de equipo ha sido avisado.${r.resumen ? ` ${r.resumen}` : ''}`
            })
          }
        />
      )}
    </div>
  )
}

function SelectorOperario({ operarios, valor, onCambio }: { operarios: { id: number; codigo: string; nombre: string; turno: string | null }[]; valor: number | null; onCambio: (id: number) => void }) {
  return (
    <label className="campo">
      Operario
      <select value={valor ?? ''} onChange={(e) => onCambio(Number(e.target.value))}>
        <option value="" disabled>
          Elegir operario…
        </option>
        {operarios.map((o) => (
          <option key={o.id} value={o.id}>
            {o.codigo} · {o.nombre} ({o.turno ?? '—'})
          </option>
        ))}
      </select>
    </label>
  )
}

function DialogoPausa({ ocupado, onCerrar, onAceptar }: { ocupado: boolean; onCerrar: () => void; onAceptar: (motivo: string) => void }) {
  const motivos = ['Descanso', 'Esperando material', 'Esperando grúa / ayuda', 'Cambio de herramienta', 'Otro trabajo urgente']
  return (
    <Modal titulo="¿Por qué pausas?" onCerrar={onCerrar}>
      <div className="botones-grandes">
        {motivos.map((m) => (
          <button key={m} disabled={ocupado} onClick={() => onAceptar(m)} style={{ fontSize: 17, padding: 16 }}>
            {m}
          </button>
        ))}
      </div>
    </Modal>
  )
}

function DialogoTerminar({ t, ocupado, onCerrar, onAceptar }: { t: Tarjeta; ocupado: boolean; onCerrar: () => void; onAceptar: (cantidad: number | null, parcial: boolean) => void }) {
  const pendiente = t.cantidad != null ? Math.max(0, t.cantidad - (t.cantidad_hecha ?? 0)) : null
  const [cantidad, setCantidad] = useState(pendiente != null ? String(pendiente) : '')
  const n = cantidad === '' ? null : Number(cantidad)
  const parcial = pendiente != null && n != null && n < pendiente
  return (
    <Modal titulo={`Terminar OF ${t.of} · ${t.operacion}`} onCerrar={onCerrar}>
      <label className="campo" style={{ fontSize: 18 }}>
        Cantidad hecha
        <input type="number" min="0" value={cantidad} onChange={(e) => setCantidad(e.target.value)} style={{ fontSize: 24, padding: 10 }} autoFocus />
      </label>
      {parcial && <div className="mensaje aviso">{pendiente! - n! === 1 ? 'Falta 1 unidad' : `Faltan ${pendiente! - n!} unidades`}: se registrará como parcial y la operación seguirá pendiente.</div>}
      <div className="botones-grandes">
        <button className="btn-terminar" disabled={ocupado} onClick={() => onAceptar(n, parcial)}>
          {parcial ? 'REGISTRAR PARCIAL' : 'TERMINAR'}
        </button>
        <button onClick={onCerrar}>Volver</button>
      </div>
    </Modal>
  )
}

function DialogoIncidencia({ ocupado, onCerrar, onAceptar }: { ocupado: boolean; onCerrar: () => void; onAceptar: (tipo: string, descripcion: string, horas: number | null) => void }) {
  const [tipo, setTipo] = useState<string | null>(null)
  const [descripcion, setDescripcion] = useState('')
  const [horasEst, setHorasEst] = useState('')
  return (
    <Modal titulo="Incidencia" onCerrar={onCerrar}>
      {!tipo ? (
        <div className="botones-grandes">
          {TIPOS_INCIDENCIA.map(([k, txt]) => (
            <button key={k} className={k === 'AVERIA' ? 'btn-incidencia' : ''} onClick={() => setTipo(k)} style={{ fontSize: 18 }}>
              {txt}
            </button>
          ))}
        </div>
      ) : (
        <>
          <p style={{ fontSize: 18 }}>
            <strong>{TIPOS_INCIDENCIA.find((x) => x[0] === tipo)?.[1]}</strong>
          </p>
          <label className="campo" style={{ fontSize: 16 }}>
            Qué pasa
            <textarea value={descripcion} onChange={(e) => setDescripcion(e.target.value)} style={{ fontSize: 17 }} autoFocus />
          </label>
          {tipo === 'AVERIA' && (
            <label className="campo" style={{ fontSize: 16, marginTop: 8 }}>
              ¿Cuántas horas crees que estará parada? (vacío si no lo sabes)
              <input type="number" min="0" step="0.5" value={horasEst} onChange={(e) => setHorasEst(e.target.value)} style={{ fontSize: 20 }} />
            </label>
          )}
          <div className="botones-grandes">
            <button className="btn-incidencia" disabled={ocupado || !descripcion.trim()} onClick={() => onAceptar(tipo, descripcion.trim(), horasEst ? Number(horasEst) : null)}>
              AVISAR
            </button>
            <button onClick={() => setTipo(null)}>Volver</button>
          </div>
        </>
      )}
    </Modal>
  )
}
