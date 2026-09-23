import { useMemo, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { api, puede } from '../api'
import { useSesion } from '../App'
import { Cargando, ExplicacionDecision, MensajeError, Modal, Riesgo, useDatos } from '../componentes/comunes'
import Gantt, { type OperarioGantt, type Vista, type Zoom } from '../componentes/Gantt'
import { fecha, isoLocal, ORDEN_NIVEL } from '../formato'
import type { Asignacion, Cambio, NoPlanificada, RecursoGantt } from '../tipos'
import { TablaCambios } from './ControlTower'
import { aCsv, descargar } from '../plataforma'

interface DatosGantt {
  plan_id: number | null
  ahora: string
  asignaciones: Asignacion[]
  recursos: RecursoGantt[]
  turnos: { turno: string; inicio: string; fin: string; extra?: boolean }[]
  no_planificadas: number
  dependencias?: [number, number][]
  limites?: { semana: string; fecha: string }[]
  operarios?: OperarioGantt[]
}

/** OF anteriores y posteriores (transitivamente) según el grafo de dependencias. */
function cadenaDe(ofId: number, deps: [number, number][]) {
  const pred = new Map<number, number[]>()
  const suc = new Map<number, number[]>()
  for (const [o, d] of deps) {
    suc.set(o, [...(suc.get(o) ?? []), d])
    pred.set(d, [...(pred.get(d) ?? []), o])
  }
  const recorrer = (mapa: Map<number, number[]>) => {
    const vistos = new Set<number>()
    const pila = [...(mapa.get(ofId) ?? [])]
    while (pila.length) {
      const x = pila.pop()!
      if (vistos.has(x) || x === ofId) continue
      vistos.add(x)
      pila.push(...(mapa.get(x) ?? []))
    }
    return vistos
  }
  return { antes: recorrer(pred), despues: recorrer(suc) }
}

interface Operario {
  id: number
  codigo: string
  nombre: string
  turno: string | null
  cualificaciones: { recurso: string | null; operacion: string | null }[]
}

export default function PlanGantt() {
  const { sesion } = useSesion()
  const [zoom, setZoom] = useState<Zoom>('turno')
  const [vista, setVista] = useState<Vista>('recurso')
  const [seccion, setSeccion] = useState('')
  const { datos, error, recargar } = useDatos(() => api.get<DatosGantt>(`/plan/activo/gantt${seccion ? `?seccion=${seccion}` : ''}`), [seccion])
  const noPlan = useDatos(() => api.get<NoPlanificada[]>('/plan/activo/no-planificadas'), [])
  const [sel, setSel] = useState<Asignacion | null>(null)
  const [mover, setMover] = useState<{ a: Asignacion; inicio: Date } | null>(null)
  const [verNoPlan, setVerNoPlan] = useState(false)
  const [params] = useSearchParams()
  const [filtro, setFiltro] = useState({ tanda: '', aparato: '', riesgo: '', texto: params.get('buscar') ?? '', problemas: false, conCarga: false })
  const [cadena, setCadena] = useState<Asignacion | null>(null)

  const visibles = useMemo(() => {
    if (!datos) return []
    const texto = filtro.texto.trim().toLowerCase()
    return datos.asignaciones.filter(
      (a) =>
        (!filtro.tanda || a.tanda === filtro.tanda) &&
        (!filtro.aparato || a.aparato === filtro.aparato) &&
        (!filtro.riesgo || (ORDEN_NIVEL[a.riesgo] ?? 0) >= ORDEN_NIVEL[filtro.riesgo]) &&
        (!texto || [a.of, a.grupo_hf, a.tipo, a.recurso, a.operario].some((v) => v?.toLowerCase().includes(texto))) &&
        (!filtro.problemas || a.provisional || a.urgente || a.riesgo === 'ROJO' || a.riesgo === 'NARANJA'),
    )
  }, [datos, filtro])

  const infoCadena = useMemo(() => {
    if (!cadena || !datos) return null
    const { antes, despues } = cadenaDe(cadena.of_id, datos.dependencias ?? [])
    const ofs = new Set([cadena.of_id, ...antes, ...despues])
    return { antes: antes.size, despues: despues.size, ops: new Set(datos.asignaciones.filter((a) => ofs.has(a.of_id)).map((a) => a.operacion_id)) }
  }, [cadena, datos])

  if (error) return <MensajeError error={error} />
  if (!datos) return <Cargando />
  if (!datos.plan_id)
    return (
      <div className="panel">
        No hay plan activo. Genéralo desde el <Link to="/">Control Tower</Link>.
      </div>
    )
  const secciones = [...new Set(datos.recursos.map((r) => r.seccion).filter(Boolean))] as string[]
  const recursosVisibles = seccion ? datos.recursos.filter((r) => r.seccion === seccion) : datos.recursos
  const tandas = [...new Set(datos.asignaciones.map((a) => a.tanda).filter(Boolean))].sort() as string[]
  const aparatos = [...new Set(datos.asignaciones.filter((a) => !filtro.tanda || a.tanda === filtro.tanda).map((a) => a.aparato).filter(Boolean))].sort() as string[]
  const filtrando = !!(filtro.tanda || filtro.aparato || filtro.riesgo || filtro.texto || filtro.problemas)
  return (
    <>
      <div className="cabecera">
        <div>
          <h1>Plan · Gantt</h1>
          <div className="sub">
            {datos.asignaciones.length} operaciones planificadas ·{' '}
            <a style={{ cursor: 'pointer' }} onClick={() => setVerNoPlan(true)}>
              {datos.no_planificadas} no planificables
            </a>{' '}
            · arrastra una barra para reprogramarla (se valida con las restricciones duras) · rayado = provisional (pendiente de programación) · borde = bloqueada
          </div>
        </div>
        <div className="botones">
          <select value={vista} onChange={(e) => setVista(e.target.value as Vista)}>
            <option value="recurso">Por recurso</option>
            <option value="operario">Por operario</option>
            <option value="tanda">Por tanda / aparato / OF</option>
          </select>
          <select value={seccion} onChange={(e) => setSeccion(e.target.value)}>
            <option value="">Todas las secciones</option>
            {secciones.map((s) => (
              <option key={s}>{s}</option>
            ))}
          </select>
          <div className="botones" role="group" aria-label="Zoom">
            {(['hora', 'turno', 'dia', 'semana'] as Zoom[]).map((z) => (
              <button key={z} className={zoom === z ? 'primario' : ''} onClick={() => setZoom(z)}>
                {{ hora: 'Hora', turno: 'Turno', dia: 'Día', semana: 'Semana' }[z]}
              </button>
            ))}
          </div>
          <button onClick={recargar}>Actualizar</button>
          <button
            onClick={() =>
              descargar(
                'plan.csv',
                aCsv(datos.asignaciones as unknown as Record<string, unknown>[], [
                  ['inicio', 'Inicio'],
                  ['fin', 'Fin'],
                  ['minutos', 'Minutos'],
                  ['recurso', 'Recurso'],
                  ['operario', 'Operario'],
                  ['of', 'OF'],
                  ['tipo', 'Operación'],
                  ['seccion', 'Sección'],
                  ['tanda', 'Tanda'],
                  ['aparato', 'Aparato'],
                  ['riesgo', 'Riesgo'],
                  ['provisional', 'Provisional'],
                  ['bloqueada', 'Bloqueada'],
                ]),
                'text/csv',
              )
            }
          >
            Exportar plan (CSV)
          </button>
        </div>
      </div>
      <div className="filtros-gantt">
        <select id="f-tanda" value={filtro.tanda} onChange={(e) => setFiltro({ ...filtro, tanda: e.target.value, aparato: '' })}>
          <option value="">Todas las tandas</option>
          {tandas.map((t) => (
            <option key={t} value={t}>
              Tanda {t}
            </option>
          ))}
        </select>
        <select id="f-aparato" value={filtro.aparato} onChange={(e) => setFiltro({ ...filtro, aparato: e.target.value })}>
          <option value="">Todos los aparatos</option>
          {aparatos.map((a) => (
            <option key={a}>{a}</option>
          ))}
        </select>
        <select id="f-riesgo" value={filtro.riesgo} onChange={(e) => setFiltro({ ...filtro, riesgo: e.target.value })}>
          <option value="">Cualquier riesgo</option>
          <option value="AMARILLO">Amarillo o peor</option>
          <option value="NARANJA">Naranja o peor</option>
          <option value="ROJO">Solo rojo</option>
        </select>
        <input id="f-texto" placeholder="Buscar OF, grupo, máquina, operario…" value={filtro.texto} onChange={(e) => setFiltro({ ...filtro, texto: e.target.value })} />
        <label>
          <input type="checkbox" checked={filtro.problemas} onChange={(e) => setFiltro({ ...filtro, problemas: e.target.checked })} /> Solo problemas
        </label>
        <label>
          <input type="checkbox" checked={filtro.conCarga} onChange={(e) => setFiltro({ ...filtro, conCarga: e.target.checked })} /> Solo filas con trabajo
        </label>
        {filtrando && (
          <span className="pequeno tenue">
            {visibles.length} de {datos.asignaciones.length} operaciones{' '}
            <button onClick={() => setFiltro({ tanda: '', aparato: '', riesgo: '', texto: '', problemas: false, conCarga: filtro.conCarga })}>Quitar filtros</button>
          </span>
        )}
      </div>
      {cadena && infoCadena && (
        <div className="mensaje aviso cadena">
          Cadena de la <strong>OF {cadena.of}</strong>: {infoCadena.antes} OF anteriores y {infoCadena.despues} posteriores ({infoCadena.ops.size} operaciones resaltadas).{' '}
          <button onClick={() => setCadena(null)}>Quitar resaltado</button>
        </div>
      )}
      <Gantt
        asignaciones={visibles}
        recursos={recursosVisibles}
        operarios={datos.operarios}
        turnos={datos.turnos}
        limites={datos.limites}
        ahora={datos.ahora}
        zoom={zoom}
        vista={vista}
        seleccion={sel?.operacion_id ?? null}
        resaltadas={infoCadena?.ops ?? null}
        soloConCarga={filtro.conCarga || filtrando}
        onSeleccionar={setSel}
        onMover={puede(sesion, 'modificar_plan') ? (a, inicio) => setMover({ a, inicio }) : undefined}
      />
      {sel && (
        <DetalleAsignacion
          a={sel}
          onVerCadena={() => {
            setCadena(sel)
            setSel(null)
          }}
          recursos={datos.recursos}
          puedeModificar={puede(sesion, 'modificar_plan')}
          onCerrar={() => setSel(null)}
          onCambio={() => {
            setSel(null)
            recargar()
          }}
        />
      )}
      {mover && (
        <ConfirmarMovimiento
          a={mover.a}
          inicio={mover.inicio}
          onCerrar={() => setMover(null)}
          onHecho={() => {
            setMover(null)
            recargar()
          }}
        />
      )}
      {verNoPlan && (
        <Modal titulo="Operaciones no planificables" onCerrar={() => setVerNoPlan(false)}>
          <p className="tenue">No se inventan datos: estas operaciones quedan fuera del plan hasta resolver el motivo.</p>
          <table>
            <thead>
              <tr>
                <th>OF</th>
                <th>Operación</th>
                <th>Motivo</th>
                <th>Detalle</th>
              </tr>
            </thead>
            <tbody>
              {(noPlan.datos ?? []).map((n) => (
                <tr key={n.operacion_id}>
                  <td>
                    <Link to={`/ofs/${n.of_id}`}>{n.of}</Link>
                  </td>
                  <td>{n.tipo}</td>
                  <td className="mono">{n.motivo}</td>
                  <td className="pequeno">{n.detalle}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </Modal>
      )}
    </>
  )
}

function ConfirmarMovimiento({ a, inicio, onCerrar, onHecho }: { a: Asignacion; inicio: Date; onCerrar: () => void; onHecho: () => void }) {
  const [motivo, setMotivo] = useState('')
  const [bloquear, setBloquear] = useState(true)
  const [err, setErr] = useState<unknown>(null)
  const [cambios, setCambios] = useState<Cambio[] | null>(null)
  const [avisos, setAvisos] = useState<string[]>([])
  return (
    <Modal titulo={`Reprogramar OF ${a.of} · ${a.tipo}`} onCerrar={cambios ? onHecho : onCerrar}>
      <p>
        ANTES: <strong>{fecha(a.inicio)}</strong> en {a.recurso} → DESPUÉS: <strong>{fecha(inicio.toISOString())}</strong>
      </p>
      {!cambios && (
        <>
          <label className="campo">
            Motivo del cambio (obligatorio, queda registrado)
            <textarea value={motivo} onChange={(e) => setMotivo(e.target.value)} autoFocus />
          </label>
          <label className="campo" style={{ flexDirection: 'row', gap: 8, marginTop: 6 }}>
            <input type="checkbox" checked={bloquear} onChange={(e) => setBloquear(e.target.checked)} /> Bloquear en esta posición (el sistema no la moverá al replanificar)
          </label>
          <MensajeError error={err} />
          <div className="botones" style={{ marginTop: 10 }}>
            <button
              className="primario"
              disabled={!motivo}
              onClick={async () => {
                try {
                  const r = await api.post<{ cambios: Cambio[]; avisos: string[] }>(`/plan/asignaciones/${a.operacion_id}/mover`, { inicio: isoLocal(inicio), motivo, bloquear })
                  setCambios(r.cambios)
                  setAvisos(r.avisos)
                } catch (e) {
                  setErr(e)
                }
              }}
            >
              Aplicar
            </button>
            <button onClick={onCerrar}>Cancelar</button>
          </div>
        </>
      )}
      {cambios && (
        <>
          <div className="mensaje ok">Cambio aplicado. Se han recolocado solo las operaciones afectadas.</div>
          {avisos.length > 0 && (
            <div className="mensaje aviso">
              <ul>
                {avisos.map((x, i) => (
                  <li key={i}>{x}</li>
                ))}
              </ul>
            </div>
          )}
          <TablaCambios cambios={cambios} />
          <button onClick={onHecho} style={{ marginTop: 10 }}>
            Cerrar
          </button>
        </>
      )}
    </Modal>
  )
}

function DetalleAsignacion({
  a,
  recursos,
  puedeModificar,
  onCerrar,
  onCambio,
  onVerCadena,
}: {
  a: Asignacion
  recursos: RecursoGantt[]
  puedeModificar: boolean
  onCerrar: () => void
  onCambio: () => void
  onVerCadena: () => void
}) {
  const { datos } = useDatos(() => api.get<Asignacion>(`/plan/asignaciones/${a.operacion_id}`), [a.operacion_id])
  const operarios = useDatos(() => api.get<Operario[]>('/operarios'), [])
  const [recurso, setRecurso] = useState<number | ''>(a.recurso_id ?? '')
  const [operario, setOperario] = useState<number | ''>(a.operario_id ?? '')
  const [inicio, setInicio] = useState(isoLocal(new Date(a.inicio)))
  const [motivo, setMotivo] = useState('')
  const [err, setErr] = useState<unknown>(null)
  const mismos = recursos.filter((r) => r.seccion === a.seccion)
  return (
    <Modal titulo={`OF ${a.of} · ${a.tipo}`} onCerrar={onCerrar}>
      <p>
        {fecha(a.inicio)} → {fecha(a.fin)} ({a.minutos} min) en <strong>{a.recurso}</strong> {a.operario && <>· {a.operario}</>} · tanda {a.tanda} · {a.aparato} · <Riesgo nivel={a.riesgo} />{' '}
        <Link to={`/ofs/${a.of_id}`}>ver OF</Link> · <a style={{ cursor: 'pointer' }} onClick={onVerCadena}>ver su cadena en el Gantt</a>
      </p>
      {datos ? <ExplicacionDecision e={datos.explicacion} /> : <Cargando />}
      {puedeModificar && (
        <details style={{ marginTop: 12 }}>
          <summary>
            <strong>Modificar (pasa por el motor de restricciones)</strong>
          </summary>
          <div className="formulario" style={{ marginTop: 8 }}>
            <label className="campo">
              Inicio
              <input type="datetime-local" value={inicio} onChange={(e) => setInicio(e.target.value)} />
            </label>
            <label className="campo">
              Recurso
              <select value={recurso} onChange={(e) => setRecurso(Number(e.target.value))}>
                {mismos.map((r) => (
                  <option key={r.id} value={r.id}>
                    {r.codigo} {r.estado !== 'OPERATIVO' ? `(${r.estado})` : ''}
                  </option>
                ))}
              </select>
            </label>
            <label className="campo">
              Operario
              <select value={operario} onChange={(e) => setOperario(Number(e.target.value))}>
                {(operarios.datos ?? []).map((o) => (
                  <option key={o.id} value={o.id}>
                    {o.nombre} ({o.turno})
                  </option>
                ))}
              </select>
            </label>
          </div>
          <label className="campo" style={{ marginTop: 8 }}>
            Motivo (obligatorio)
            <textarea value={motivo} onChange={(e) => setMotivo(e.target.value)} />
          </label>
          <MensajeError error={err} />
          <div className="botones" style={{ marginTop: 8 }}>
            <button
              className="primario"
              disabled={!motivo}
              onClick={async () => {
                try {
                  await api.post(`/plan/asignaciones/${a.operacion_id}/mover`, { inicio, recurso_id: recurso || null, operario_id: operario || null, motivo, bloquear: true })
                  onCambio()
                } catch (e) {
                  setErr(e)
                }
              }}
            >
              Aplicar cambio
            </button>
            <button
              onClick={async () => {
                try {
                  await api.post(`/plan/asignaciones/${a.operacion_id}/bloquear`, { bloqueada: !a.bloqueada, motivo: motivo || null })
                  onCambio()
                } catch (e) {
                  setErr(e)
                }
              }}
            >
              {a.bloqueada ? 'Desbloquear' : 'Bloquear en su posición'}
            </button>
          </div>
        </details>
      )}
    </Modal>
  )
}
