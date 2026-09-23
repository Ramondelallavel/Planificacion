import { useState } from 'react'
import { api, puede } from '../api'
import { useSesion } from '../App'
import { Cargando, MensajeError, Modal, useDatos } from '../componentes/comunes'
import { fecha } from '../formato'

interface Recurso {
  id: number
  codigo: string
  nombre: string
  tipo: string
  seccion: string | null
  capacidad: number
  estado: string
  operaciones: string[] | null
  alias: string[] | null
  turnos: string[] | null
  requiere_operario: boolean
  activo: boolean
  fuente: string | null
  parada_actual: { inicio: string; fin: string | null; motivo: string } | null
}

interface Operario {
  id: number
  codigo: string
  nombre: string
  turno: string | null
  seccion: string | null
  activo: boolean
  cualificaciones: { recurso: string | null; operacion: string | null; nivel: number | null }[]
  ausente: { motivo: string; fin: string | null } | null
}

interface Turno {
  codigo: string
  nombre: string
  hora_inicio: string
  hora_fin: string
  dias_semana: number[]
  pausas: { inicio: string; fin: string }[] | null
  activo: boolean
}

interface Seccion {
  codigo: string
  codigo_completo: string | null
  nombre: string | null
  flujo: string | null
  requiere_programacion: boolean
  conocida: boolean
  fuente: string | null
}

interface Tiempo {
  id: number
  seccion: string
  grupo_hf: string | null
  articulo: string | null
  tipo_operacion: string | null
  minutos_preparacion: number
  minutos_por_unidad: number
  minutos_por_linea: number
  fuente: string | null
  es_ejemplo: boolean
  version: number
  vigente: boolean
  creado: string
  creado_por: string | null
  notas: string | null
}

type Parametros = Record<string, { descripcion: string; valor: Record<string, unknown>; version: number; es_defecto: boolean }>

const PESTANAS: [string, string][] = [
  ['recursos', 'Recursos / máquinas'],
  ['operarios', 'Operarios y cualificaciones'],
  ['turnos', 'Turnos'],
  ['calendario', 'Calendario laboral'],
  ['secciones', 'Secciones'],
  ['tiempos', 'Tiempos estándar'],
  ['parametros', 'Parámetros de planificación'],
  ['integraciones', 'Integraciones'],
  ['aprendizaje', 'Aprendizaje de tiempos'],
]

const DIAS = ['L', 'M', 'X', 'J', 'V', 'S', 'D']
const lista = (v: string) =>
  v
    .split(',')
    .map((x) => x.trim())
    .filter(Boolean)

export default function Configuracion() {
  const [pestana, setPestana] = useState('recursos')
  return (
    <>
      <div className="cabecera">
        <div>
          <h1>Configuración de fábrica</h1>
          <div className="sub">Todo cambio queda registrado en la auditoría. Los valores marcados EJEMPLO no son datos reales de HIDRAL: sustitúyelos antes de usar el plan.</div>
        </div>
      </div>
      <div className="pestanas">
        {PESTANAS.map(([k, t]) => (
          <button key={k} className={pestana === k ? 'activa' : ''} onClick={() => setPestana(k)}>
            {t}
          </button>
        ))}
      </div>
      {pestana === 'recursos' && <Recursos />}
      {pestana === 'operarios' && <Operarios />}
      {pestana === 'turnos' && <Turnos />}
      {pestana === 'calendario' && <Calendario />}
      {pestana === 'secciones' && <Secciones />}
      {pestana === 'tiempos' && <Tiempos />}
      {pestana === 'parametros' && <ParametrosPlan />}
      {pestana === 'integraciones' && <Integraciones />}
      {pestana === 'aprendizaje' && <Aprendizaje />}
    </>
  )
}

// ------------------------------------------------------------------ recursos
function Recursos() {
  const { sesion } = useSesion()
  const { datos, error, recargar } = useDatos(() => api.get<Recurso[]>('/recursos'), [])
  const [editar, setEditar] = useState<Recurso | 'nuevo' | null>(null)
  const editable = puede(sesion, 'recursos')
  return (
    <section className="panel">
      <div className="cabecera">
        <h2>Recursos</h2>
        {editable && (
          <button className="primario" onClick={() => setEditar('nuevo')}>
            Nuevo recurso
          </button>
        )}
      </div>
      <MensajeError error={error} />
      {!datos ? (
        <Cargando />
      ) : (
        <table>
          <thead>
            <tr>
              <th>Código</th>
              <th>Nombre</th>
              <th>Sección</th>
              <th>Tipo</th>
              <th>Cap.</th>
              <th>Operaciones</th>
              <th>Alias en PDF</th>
              <th>Turnos</th>
              <th>Estado</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {datos.map((r) => (
              <tr key={r.id} className={r.activo ? '' : 'tenue'}>
                <td className="mono">{r.codigo}</td>
                <td>
                  {r.nombre}
                </td>
                <td>{r.seccion}</td>
                <td className="pequeno">{r.tipo}</td>
                <td>{r.capacidad}</td>
                <td className="pequeno">{(r.operaciones ?? []).join(', ') || <span className="nd">—</span>}</td>
                <td className="pequeno mono">{(r.alias ?? []).join(', ')}</td>
                <td className="pequeno">{(r.turnos ?? []).join(', ') || 'todos'}</td>
                <td>
                  <span className="etiqueta">{r.estado}</span>
                  {r.parada_actual && (
                    <div className="pequeno tenue">
                      {r.parada_actual.motivo} hasta {r.parada_actual.fin ? fecha(r.parada_actual.fin) : 'sin fin'}
                    </div>
                  )}
                </td>
                <td>{editable && <button onClick={() => setEditar(r)}>Editar</button>}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {editar && (
        <EditarRecurso
          r={editar === 'nuevo' ? null : editar}
          onCerrar={() => setEditar(null)}
          onHecho={() => {
            setEditar(null)
            recargar()
          }}
        />
      )}
    </section>
  )
}

function EditarRecurso({ r, onCerrar, onHecho }: { r: Recurso | null; onCerrar: () => void; onHecho: () => void }) {
  const [f, setF] = useState({
    codigo: r?.codigo ?? '',
    nombre: r?.nombre ?? '',
    seccion: r?.seccion ?? '',
    tipo: r?.tipo ?? 'MAQUINA',
    capacidad: String(r?.capacidad ?? 1),
    operaciones: (r?.operaciones ?? []).join(', '),
    alias: (r?.alias ?? []).join(', '),
    turnos: (r?.turnos ?? []).join(', '),
    requiere_operario: r?.requiere_operario ?? true,
    activo: r?.activo ?? true,
    estado: r?.estado ?? 'OPERATIVO',
  })
  const [err, setErr] = useState<unknown>(null)
  const campo = (k: keyof typeof f, etiqueta: string, ayuda?: string) => (
    <label className="campo">
      {etiqueta}
      <input value={String(f[k])} onChange={(e) => setF({ ...f, [k]: e.target.value })} placeholder={ayuda} disabled={k === 'codigo' && !!r} />
    </label>
  )
  const guardar = async () => {
    const cuerpo = {
      codigo: f.codigo,
      nombre: f.nombre,
      seccion: f.seccion,
      tipo: f.tipo,
      capacidad: Number(f.capacidad) || 1,
      operaciones: lista(f.operaciones),
      alias: lista(f.alias),
      turnos: lista(f.turnos),
      requiere_operario: f.requiere_operario,
      activo: f.activo,
      estado: f.estado,
    }
    try {
      if (r) await api.patch(`/recursos/${r.id}`, cuerpo)
      else await api.post('/recursos', cuerpo)
      onHecho()
    } catch (e) {
      setErr(e)
    }
  }
  return (
    <Modal titulo={r ? `Recurso ${r.codigo}` : 'Nuevo recurso'} onCerrar={onCerrar}>
      <div className="formulario">
        {campo('codigo', 'Código')}
        {campo('nombre', 'Nombre')}
        {campo('seccion', 'Sección', 'ELA, COR, LCH…')}
        <label className="campo">
          Tipo
          <select value={f.tipo} onChange={(e) => setF({ ...f, tipo: e.target.value })}>
            {['MAQUINA', 'PUESTO', 'PROGRAMACION'].map((t) => (
              <option key={t}>{t}</option>
            ))}
          </select>
        </label>
        {campo('capacidad', 'Capacidad (unidades en paralelo)')}
        <label className="campo">
          Estado
          <select value={f.estado} onChange={(e) => setF({ ...f, estado: e.target.value })}>
            {['OPERATIVO', 'AVERIADO', 'PARADO', 'MANTENIMIENTO'].map((t) => (
              <option key={t}>{t}</option>
            ))}
          </select>
        </label>
      </div>
      <div className="formulario" style={{ marginTop: 8 }}>
        {campo('operaciones', 'Tipos de operación que hace', 'CORTE_LASER, PLEGADO…')}
        {campo('alias', 'Alias en el PDF (columna Máquina)', 'LASERTUB, FICEP…')}
        {campo('turnos', 'Turnos en los que trabaja (vacío = todos)', 'M, T')}
      </div>
      <div className="botones" style={{ marginTop: 8 }}>
        <label>
          <input type="checkbox" checked={f.requiere_operario} onChange={(e) => setF({ ...f, requiere_operario: e.target.checked })} /> Requiere operario
        </label>
        <label>
          <input type="checkbox" checked={f.activo} onChange={(e) => setF({ ...f, activo: e.target.checked })} /> Activo
        </label>
      </div>
      <p className="pequeno tenue">Para una avería con replanificación usa Incidencias; cambiar aquí el estado no mueve el plan hasta el próximo recálculo.</p>
      <MensajeError error={err} />
      <div className="botones" style={{ marginTop: 8 }}>
        <button className="primario" onClick={guardar} disabled={!f.codigo || !f.nombre || !f.seccion}>
          Guardar
        </button>
        <button onClick={onCerrar}>Cancelar</button>
      </div>
    </Modal>
  )
}

// ------------------------------------------------------------------ operarios
function Operarios() {
  const { sesion } = useSesion()
  const { datos, error, recargar } = useDatos(() => api.get<Operario[]>('/operarios'), [])
  const [editar, setEditar] = useState<Operario | 'nuevo' | null>(null)
  const [ausencia, setAusencia] = useState<Operario | null>(null)
  const editable = puede(sesion, 'recursos')
  return (
    <section className="panel">
      <div className="cabecera">
        <h2>Operarios</h2>
        {editable && (
          <button className="primario" onClick={() => setEditar('nuevo')}>
            Nuevo operario
          </button>
        )}
      </div>
      <MensajeError error={error} />
      {!datos ? (
        <Cargando />
      ) : (
        <table>
          <thead>
            <tr>
              <th>Código</th>
              <th>Nombre</th>
              <th>Turno</th>
              <th>Sección</th>
              <th>Puede trabajar en</th>
              <th>Situación</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {datos.map((o) => (
              <tr key={o.id} className={o.activo ? '' : 'tenue'}>
                <td className="mono">{o.codigo}</td>
                <td>{o.nombre}</td>
                <td>{o.turno ?? '—'}</td>
                <td>{o.seccion ?? '—'}</td>
                <td className="pequeno">
                  {o.cualificaciones.map((c) => c.recurso ?? c.operacion).join(', ') || <span className="nd">sin cualificaciones: no se le asignará trabajo</span>}
                </td>
                <td className="pequeno">
                  {o.ausente ? (
                    <span className="riesgo NARANJA">
                      AUSENTE · {o.ausente.motivo}
                      {o.ausente.fin && ` hasta ${fecha(o.ausente.fin)}`}
                    </span>
                  ) : o.activo ? (
                    'Disponible'
                  ) : (
                    'Inactivo'
                  )}
                </td>
                <td>
                  {editable && (
                    <div className="botones">
                      <button onClick={() => setEditar(o)}>Editar</button>
                      <button onClick={() => setAusencia(o)}>Ausencia</button>
                    </div>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {editar && (
        <EditarOperario
          o={editar === 'nuevo' ? null : editar}
          onCerrar={() => setEditar(null)}
          onHecho={() => {
            setEditar(null)
            recargar()
          }}
        />
      )}
      {ausencia && (
        <NuevaAusencia
          o={ausencia}
          onCerrar={() => setAusencia(null)}
          onHecho={() => {
            setAusencia(null)
            recargar()
          }}
        />
      )}
    </section>
  )
}

function EditarOperario({ o, onCerrar, onHecho }: { o: Operario | null; onCerrar: () => void; onHecho: () => void }) {
  const [f, setF] = useState({
    codigo: o?.codigo ?? '',
    nombre: o?.nombre ?? '',
    turno: o?.turno ?? '',
    seccion: o?.seccion ?? '',
    activo: o?.activo ?? true,
    recursos: (o?.cualificaciones ?? [])
      .map((c) => c.recurso)
      .filter(Boolean)
      .join(', '),
    operaciones: (o?.cualificaciones ?? [])
      .map((c) => c.operacion)
      .filter(Boolean)
      .join(', '),
  })
  const [err, setErr] = useState<unknown>(null)
  const guardar = async () => {
    const cuerpo = { codigo: f.codigo, nombre: f.nombre, turno: f.turno || null, seccion: f.seccion || null, activo: f.activo, recursos: lista(f.recursos), operaciones: lista(f.operaciones) }
    try {
      if (o) await api.patch(`/operarios/${o.id}`, cuerpo)
      else await api.post('/operarios', cuerpo)
      onHecho()
    } catch (e) {
      setErr(e)
    }
  }
  return (
    <Modal titulo={o ? `Operario ${o.codigo}` : 'Nuevo operario'} onCerrar={onCerrar}>
      <div className="formulario">
        <label className="campo">
          Código de empleado
          <input value={f.codigo} disabled={!!o} onChange={(e) => setF({ ...f, codigo: e.target.value })} />
        </label>
        <label className="campo">
          Nombre
          <input value={f.nombre} onChange={(e) => setF({ ...f, nombre: e.target.value })} />
        </label>
        <label className="campo">
          Turno
          <input value={f.turno} onChange={(e) => setF({ ...f, turno: e.target.value })} placeholder="M, T, N" />
        </label>
        <label className="campo">
          Sección
          <input value={f.seccion} onChange={(e) => setF({ ...f, seccion: e.target.value })} />
        </label>
      </div>
      <label className="campo" style={{ marginTop: 8 }}>
        Máquinas / puestos en los que está cualificado (códigos de recurso, separados por comas)
        <input value={f.recursos} onChange={(e) => setF({ ...f, recursos: e.target.value })} />
      </label>
      <label className="campo" style={{ marginTop: 8 }}>
        Tipos de operación que puede hacer en cualquier recurso (opcional)
        <input value={f.operaciones} onChange={(e) => setF({ ...f, operaciones: e.target.value })} placeholder="SOLDADURA, MONTAJE…" />
      </label>
      <label style={{ display: 'block', marginTop: 8 }}>
        <input type="checkbox" checked={f.activo} onChange={(e) => setF({ ...f, activo: e.target.checked })} /> Activo
      </label>
      <MensajeError error={err} />
      <div className="botones" style={{ marginTop: 8 }}>
        <button className="primario" onClick={guardar} disabled={!f.codigo || !f.nombre}>
          Guardar
        </button>
        <button onClick={onCerrar}>Cancelar</button>
      </div>
    </Modal>
  )
}

function NuevaAusencia({ o, onCerrar, onHecho }: { o: Operario; onCerrar: () => void; onHecho: () => void }) {
  const [inicio, setInicio] = useState('')
  const [fin, setFin] = useState('')
  const [motivo, setMotivo] = useState('Vacaciones')
  const [err, setErr] = useState<unknown>(null)
  return (
    <Modal titulo={`Ausencia planificada · ${o.nombre}`} onCerrar={onCerrar}>
      <p className="pequeno tenue">Para una ausencia imprevista que deba replanificar el turno en curso, regístrala en Incidencias.</p>
      <div className="formulario">
        <label className="campo">
          Desde
          <input type="datetime-local" value={inicio} onChange={(e) => setInicio(e.target.value)} />
        </label>
        <label className="campo">
          Hasta (vacío = sin fecha)
          <input type="datetime-local" value={fin} onChange={(e) => setFin(e.target.value)} />
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
          disabled={!inicio || !motivo}
          onClick={async () => {
            try {
              await api.post(`/operarios/${o.id}/ausencias`, { inicio, fin: fin || null, motivo })
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

// ------------------------------------------------------------------ turnos
function Turnos() {
  const { sesion } = useSesion()
  const { datos, error, recargar } = useDatos(() => api.get<Turno[]>('/turnos'), [])
  const [editar, setEditar] = useState<Turno | null>(null)
  const editable = puede(sesion, 'recursos')
  const nuevo: Turno = { codigo: '', nombre: '', hora_inicio: '07:00', hora_fin: '15:00', dias_semana: [0, 1, 2, 3, 4], pausas: [], activo: true }
  return (
    <section className="panel">
      <div className="cabecera">
        <h2>Turnos</h2>
        {editable && (
          <button className="primario" onClick={() => setEditar(nuevo)}>
            Nuevo turno
          </button>
        )}
      </div>
      <MensajeError error={error} />
      {!datos ? (
        <Cargando />
      ) : (
        <table>
          <thead>
            <tr>
              <th>Código</th>
              <th>Nombre</th>
              <th>Horario</th>
              <th>Días</th>
              <th>Pausas</th>
              <th>Activo</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {datos.map((t) => (
              <tr key={t.codigo}>
                <td className="mono">{t.codigo}</td>
                <td>{t.nombre}</td>
                <td>
                  {t.hora_inicio}–{t.hora_fin}
                </td>
                <td>{t.dias_semana.map((d) => DIAS[d]).join(' ')}</td>
                <td className="pequeno">{(t.pausas ?? []).map((p) => `${p.inicio}–${p.fin}`).join(', ') || '—'}</td>
                <td>{t.activo ? 'Sí' : 'No'}</td>
                <td>{editable && <button onClick={() => setEditar(t)}>Editar</button>}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {editar && (
        <EditarTurno
          t={editar}
          onCerrar={() => setEditar(null)}
          onHecho={() => {
            setEditar(null)
            recargar()
          }}
        />
      )}
    </section>
  )
}

function EditarTurno({ t, onCerrar, onHecho }: { t: Turno; onCerrar: () => void; onHecho: () => void }) {
  const [f, setF] = useState({ ...t, pausasTxt: (t.pausas ?? []).map((p) => `${p.inicio}-${p.fin}`).join(', ') })
  const [err, setErr] = useState<unknown>(null)
  const guardar = async () => {
    try {
      const pausas = lista(f.pausasTxt).map((p) => {
        const [inicio, fin] = p.split('-').map((x) => x.trim())
        if (!/^\d{2}:\d{2}$/.test(inicio ?? '') || !/^\d{2}:\d{2}$/.test(fin ?? '')) throw new Error(`Pausa no válida: "${p}" (formato HH:MM-HH:MM)`)
        return { inicio, fin }
      })
      await api.put(`/turnos/${encodeURIComponent(f.codigo)}`, { codigo: f.codigo, nombre: f.nombre, hora_inicio: f.hora_inicio, hora_fin: f.hora_fin, dias_semana: f.dias_semana, pausas, activo: f.activo })
      onHecho()
    } catch (e) {
      setErr(e)
    }
  }
  return (
    <Modal titulo={t.codigo ? `Turno ${t.codigo}` : 'Nuevo turno'} onCerrar={onCerrar}>
      <div className="formulario">
        <label className="campo">
          Código
          <input value={f.codigo} disabled={!!t.codigo} onChange={(e) => setF({ ...f, codigo: e.target.value })} />
        </label>
        <label className="campo">
          Nombre
          <input value={f.nombre} onChange={(e) => setF({ ...f, nombre: e.target.value })} />
        </label>
        <label className="campo">
          Inicio
          <input type="time" value={f.hora_inicio} onChange={(e) => setF({ ...f, hora_inicio: e.target.value })} />
        </label>
        <label className="campo">
          Fin (si es menor que el inicio, termina al día siguiente)
          <input type="time" value={f.hora_fin} onChange={(e) => setF({ ...f, hora_fin: e.target.value })} />
        </label>
      </div>
      <div className="botones" style={{ marginTop: 8 }}>
        {DIAS.map((d, i) => (
          <label key={d}>
            <input
              type="checkbox"
              checked={f.dias_semana.includes(i)}
              onChange={(e) => setF({ ...f, dias_semana: e.target.checked ? [...f.dias_semana, i].sort() : f.dias_semana.filter((x) => x !== i) })}
            />{' '}
            {d}
          </label>
        ))}
      </div>
      <label className="campo" style={{ marginTop: 8 }}>
        Pausas (HH:MM-HH:MM separadas por comas)
        <input value={f.pausasTxt} onChange={(e) => setF({ ...f, pausasTxt: e.target.value })} placeholder="10:00-10:20" />
      </label>
      <label style={{ display: 'block', marginTop: 8 }}>
        <input type="checkbox" checked={f.activo} onChange={(e) => setF({ ...f, activo: e.target.checked })} /> Activo
      </label>
      <MensajeError error={err} />
      <div className="botones" style={{ marginTop: 8 }}>
        <button className="primario" onClick={guardar} disabled={!f.codigo || !f.nombre}>
          Guardar
        </button>
        <button onClick={onCerrar}>Cancelar</button>
      </div>
    </Modal>
  )
}

// ------------------------------------------------------------------ calendario laboral
interface DatosCalendario {
  festivos: { fecha: string; descripcion: string | null }[]
  jornadas_extra: { id: number; fecha: string; turno: string; secciones: string[] | null; motivo: string | null; creado_por: string | null }[]
}

const diaLargo = (iso: string) => new Date(iso + 'T12:00:00').toLocaleDateString('es-ES', { weekday: 'short', day: '2-digit', month: '2-digit', year: 'numeric' })

function Calendario() {
  const { sesion } = useSesion()
  const editable = puede(sesion, 'recursos')
  const { datos, error, recargar } = useDatos(() => api.get<DatosCalendario>('/calendario'), [])
  const turnos = useDatos(() => api.get<Turno[]>('/turnos'), [])
  const secciones = useDatos(() => api.get<Seccion[]>('/secciones'), [])
  const [festivo, setFestivo] = useState({ fecha: '', descripcion: '' })
  const [extra, setExtra] = useState({ fecha: '', turno: '', secciones: [] as string[], motivo: '' })
  const [msg, setMsg] = useState<string | null>(null)
  const [err, setErr] = useState<unknown>(null)
  const hacer = async (f: () => Promise<{ aviso?: string } | unknown>) => {
    setErr(null)
    setMsg(null)
    try {
      const r = (await f()) as { aviso?: string } | undefined
      if (r?.aviso) setMsg(r.aviso)
      recargar()
    } catch (e) {
      setErr(e)
    }
  }
  const turnoPorDefecto = turnos.datos?.find((t) => t.activo)?.codigo ?? ''
  return (
    <>
      <p className="pequeno tenue">
        El planificador trabaja con los turnos y días de cada turno. Aquí se añaden las excepciones: <strong>festivos</strong> (no se trabaja) y <strong>jornadas extra</strong> (se trabaja un
        turno fuera del calendario habitual, en toda la fábrica o solo en algunas secciones; lo hacen los operarios de ese turno que trabajan en esas secciones). Para ver antes su efecto,
        simúlalo en <em>Simulación → ¿Y si hago un turno extra…?</em>
      </p>
      {msg && <div className="mensaje ok">{msg}</div>}
      <MensajeError error={error ?? err} />
      <div className="rejilla dos">
        <section className="panel">
          <h2>Jornadas extra</h2>
          {!datos ? (
            <Cargando />
          ) : datos.jornadas_extra.length === 0 ? (
            <p className="tenue">No hay jornadas extra programadas.</p>
          ) : (
            <table>
              <thead>
                <tr>
                  <th>Día</th>
                  <th>Turno</th>
                  <th>Dónde</th>
                  <th>Motivo</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {datos.jornadas_extra.map((j) => (
                  <tr key={j.id}>
                    <td>{diaLargo(j.fecha)}</td>
                    <td>{turnos.datos?.find((t) => t.codigo === j.turno)?.nombre ?? j.turno}</td>
                    <td>{j.secciones?.join(', ') ?? 'Toda la fábrica'}</td>
                    <td className="pequeno">
                      {j.motivo ?? '—'}
                      {j.creado_por && <div className="tenue">por {j.creado_por}</div>}
                    </td>
                    <td>{editable && <button onClick={() => hacer(() => api.del(`/calendario/jornadas-extra/${j.id}`))}>Quitar</button>}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
          {editable && (
            <div style={{ marginTop: 12 }}>
              <div className="formulario">
                <label className="campo">
                  Día
                  <input id="extra-dia" type="date" value={extra.fecha} onChange={(e) => setExtra({ ...extra, fecha: e.target.value })} />
                </label>
                <label className="campo">
                  Turno
                  <select id="extra-turno-cal" value={extra.turno || turnoPorDefecto} onChange={(e) => setExtra({ ...extra, turno: e.target.value })}>
                    {(turnos.datos ?? [])
                      .filter((t) => t.activo)
                      .map((t) => (
                        <option key={t.codigo} value={t.codigo}>
                          {t.nombre} ({t.hora_inicio}–{t.hora_fin})
                        </option>
                      ))}
                  </select>
                </label>
                <label className="campo">
                  Motivo
                  <input id="extra-motivo" value={extra.motivo} onChange={(e) => setExtra({ ...extra, motivo: e.target.value })} placeholder="Recuperar la semana 40" />
                </label>
              </div>
              <fieldset className="secciones-extra">
                <legend className="pequeno">Secciones (ninguna marcada = toda la fábrica)</legend>
                {(secciones.datos ?? []).map((x) => (
                  <label key={x.codigo}>
                    <input
                      type="checkbox"
                      checked={extra.secciones.includes(x.codigo)}
                      onChange={(e) => setExtra({ ...extra, secciones: e.target.checked ? [...extra.secciones, x.codigo] : extra.secciones.filter((c) => c !== x.codigo) })}
                    />{' '}
                    {x.codigo}
                  </label>
                ))}
              </fieldset>
              <button
                className="primario"
                disabled={!extra.fecha}
                onClick={() =>
                  hacer(async () => {
                    const r = await api.post('/calendario/jornadas-extra', {
                      fecha: extra.fecha,
                      turno: extra.turno || turnoPorDefecto,
                      secciones: extra.secciones.length ? extra.secciones : null,
                      motivo: extra.motivo || null,
                    })
                    setExtra({ fecha: '', turno: '', secciones: [], motivo: '' })
                    return r
                  })
                }
              >
                Añadir jornada extra
              </button>
            </div>
          )}
        </section>
        <section className="panel">
          <h2>Festivos</h2>
          {!datos ? (
            <Cargando />
          ) : datos.festivos.length === 0 ? (
            <p className="tenue">No hay festivos a partir de este mes.</p>
          ) : (
            <table>
              <tbody>
                {datos.festivos.map((f) => (
                  <tr key={f.fecha}>
                    <td>{diaLargo(f.fecha)}</td>
                    <td>{f.descripcion ?? '—'}</td>
                    <td>{editable && <button onClick={() => hacer(() => api.del(`/calendario/festivos/${f.fecha}`))}>Quitar</button>}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
          {editable && (
            <div className="botones" style={{ marginTop: 12 }}>
              <input id="festivo-fecha" type="date" value={festivo.fecha} onChange={(e) => setFestivo({ ...festivo, fecha: e.target.value })} />
              <input id="festivo-descripcion" placeholder="Descripción" value={festivo.descripcion} onChange={(e) => setFestivo({ ...festivo, descripcion: e.target.value })} />
              <button
                className="primario"
                disabled={!festivo.fecha}
                onClick={() =>
                  hacer(async () => {
                    const r = await api.post('/calendario/festivos', { fecha: festivo.fecha, descripcion: festivo.descripcion || null })
                    setFestivo({ fecha: '', descripcion: '' })
                    return r
                  })
                }
              >
                Añadir festivo
              </button>
            </div>
          )}
        </section>
      </div>
    </>
  )
}

// ------------------------------------------------------------------ secciones
function Secciones() {
  const { sesion } = useSesion()
  const { datos, error, recargar } = useDatos(() => api.get<Seccion[]>('/secciones'), [])
  const [err, setErr] = useState<unknown>(null)
  const editable = puede(sesion, 'recursos')
  const cambiar = async (codigo: string, cuerpo: Partial<Seccion>) => {
    try {
      await api.patch(`/secciones/${encodeURIComponent(codigo)}`, cuerpo)
      recargar()
    } catch (e) {
      setErr(e)
    }
  }
  return (
    <section className="panel">
      <h2>Secciones</h2>
      <p className="pequeno tenue">
        Las secciones aparecen al importar documentos. Una sección <strong>desconocida</strong> se detectó en un PDF pero nadie la ha configurado: revisa su flujo y si requiere programación CNC.
      </p>
      <MensajeError error={error ?? err} />
      {!datos ? (
        <Cargando />
      ) : (
        <table>
          <thead>
            <tr>
              <th>Código</th>
              <th>Código completo</th>
              <th>Nombre</th>
              <th>Flujo</th>
              <th>Requiere programación</th>
              <th>Estado</th>
            </tr>
          </thead>
          <tbody>
            {datos.map((x) => (
              <tr key={x.codigo}>
                <td className="mono">{x.codigo}</td>
                <td className="mono pequeno">{x.codigo_completo ?? '—'}</td>
                <td>
                  {editable ? (
                    <input defaultValue={x.nombre ?? ''} onBlur={(e) => e.target.value !== (x.nombre ?? '') && cambiar(x.codigo, { nombre: e.target.value })} />
                  ) : (
                    x.nombre
                  )}
                </td>
                <td>
                  {editable ? (
                    <select value={x.flujo ?? ''} onChange={(e) => cambiar(x.codigo, { flujo: e.target.value || null })}>
                      <option value="">Estándar</option>
                      <option value="LCH">LCH / LaserTub (programación previa)</option>
                    </select>
                  ) : (
                    x.flujo ?? 'Estándar'
                  )}
                </td>
                <td>
                  <input type="checkbox" disabled={!editable} checked={x.requiere_programacion} onChange={(e) => cambiar(x.codigo, { requiere_programacion: e.target.checked })} />
                </td>
                <td>{x.conocida ? <span className="etiqueta">configurada</span> : <span className="riesgo AMARILLO">REVISIÓN NECESARIA</span>}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </section>
  )
}

// ------------------------------------------------------------------ tiempos estándar
function Tiempos() {
  const { sesion } = useSesion()
  const [todos, setTodos] = useState(false)
  const { datos, error, recargar } = useDatos(() => api.get<Tiempo[]>(`/tiempos-estandar${todos ? '?todos=true' : ''}`), [todos])
  const [nuevo, setNuevo] = useState<Partial<Tiempo> | null>(null)
  const [msg, setMsg] = useState<string | null>(null)
  const [err, setErr] = useState<unknown>(null)
  const configurar = puede(sesion, 'configurar')
  const aprobar = puede(sesion, 'aprobar_estimaciones')
  const hayEjemplo = (datos ?? []).some((t) => t.es_ejemplo && t.vigente)
  return (
    <section className="panel">
      <div className="cabecera">
        <h2>Tiempos estándar</h2>
        <div className="botones">
          <label>
            <input type="checkbox" checked={todos} onChange={(e) => setTodos(e.target.checked)} /> Ver histórico de versiones
          </label>
          {configurar && (
            <>
              <button className="primario" onClick={() => setNuevo({ seccion: '', minutos_preparacion: 0, minutos_por_unidad: 0, minutos_por_linea: 0 })}>
                Nuevo tiempo
              </button>
              <button
                onClick={async () => {
                  setErr(null)
                  try {
                    const r = await api.post<{ operaciones?: number; quedan_sin_tiempo: boolean }>('/tiempos-estandar/recalcular')
                    setMsg(`Operaciones recalculadas${r.quedan_sin_tiempo ? '. ATENCIÓN: quedan operaciones sin tiempo estándar (no planificables).' : '.'} Regenera el plan para aplicar las nuevas duraciones.`)
                  } catch (e) {
                    setErr(e)
                  }
                }}
              >
                Recalcular operaciones
              </button>
            </>
          )}
        </div>
      </div>
      {hayEjemplo && <div className="mensaje aviso">Hay tiempos marcados EJEMPLO: son valores ficticios de arranque, no mediciones de HIDRAL. Sustitúyelos por los tiempos reales.</div>}
      <p className="pequeno tenue">
        Duración = preparación + minutos/unidad × cantidad + minutos/línea × nº de líneas de la hoja. Se aplica el ámbito más específico (artículo &gt; grupo HF &gt; tipo de operación &gt; sección). Cada
        cambio crea una versión nueva; la anterior se conserva y se puede recuperar.
      </p>
      {msg && <div className="mensaje ok">{msg}</div>}
      <MensajeError error={error ?? err} />
      {!datos ? (
        <Cargando />
      ) : (
        <table>
          <thead>
            <tr>
              <th>Sección</th>
              <th>Grupo HF</th>
              <th>Artículo</th>
              <th>Operación</th>
              <th>Prep. (min)</th>
              <th>min/ud</th>
              <th>min/línea</th>
              <th>Versión</th>
              <th>Origen</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {datos.map((t) => (
              <tr key={t.id} className={t.vigente ? '' : 'tenue'}>
                <td>{t.seccion}</td>
                <td className="pequeno">{t.grupo_hf ?? '—'}</td>
                <td className="mono pequeno">{t.articulo ?? '—'}</td>
                <td className="pequeno">{t.tipo_operacion ?? '—'}</td>
                <td>{t.minutos_preparacion}</td>
                <td>{t.minutos_por_unidad}</td>
                <td>{t.minutos_por_linea}</td>
                <td>
                  v{t.version} {!t.vigente && <span className="etiqueta">histórico</span>}
                </td>
                <td className="pequeno">
                  {t.es_ejemplo && <span className="etiqueta ejemplo">EJEMPLO</span>} {t.fuente} {t.creado_por && `· ${t.creado_por}`}
                  {t.notas && <div className="tenue">{t.notas}</div>}
                </td>
                <td>
                  <div className="botones">
                    {configurar && t.vigente && <button onClick={() => setNuevo(t)}>Nueva versión</button>}
                    {aprobar && t.vigente && t.version > 1 && (
                      <button
                        onClick={async () => {
                          setErr(null)
                          try {
                            await api.post(`/tiempos-estandar/${t.id}/revertir`)
                            setMsg(`Recuperada la versión anterior de ${t.seccion}/${t.tipo_operacion ?? t.grupo_hf ?? '—'}`)
                            recargar()
                          } catch (e) {
                            setErr(e)
                          }
                        }}
                      >
                        Revertir
                      </button>
                    )}
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {nuevo && (
        <NuevoTiempo
          base={nuevo}
          onCerrar={() => setNuevo(null)}
          onHecho={() => {
            setNuevo(null)
            setMsg('Nueva versión guardada. Pulsa «Recalcular operaciones» para aplicarla a las OF pendientes.')
            recargar()
          }}
        />
      )}
    </section>
  )
}

function NuevoTiempo({ base, onCerrar, onHecho }: { base: Partial<Tiempo>; onCerrar: () => void; onHecho: () => void }) {
  const [f, setF] = useState({
    seccion: base.seccion ?? '',
    grupo_hf: base.grupo_hf ?? '',
    articulo: base.articulo ?? '',
    tipo_operacion: base.tipo_operacion ?? '',
    minutos_preparacion: String(base.minutos_preparacion ?? 0),
    minutos_por_unidad: String(base.minutos_por_unidad ?? 0),
    minutos_por_linea: String(base.minutos_por_linea ?? 0),
    notas: '',
  })
  const [err, setErr] = useState<unknown>(null)
  const ambitoFijo = !!base.id
  const texto = (k: keyof typeof f, etiqueta: string, fijo = false) => (
    <label className="campo">
      {etiqueta}
      <input value={f[k]} disabled={fijo} onChange={(e) => setF({ ...f, [k]: e.target.value })} />
    </label>
  )
  return (
    <Modal titulo={base.id ? 'Nueva versión de tiempo estándar' : 'Nuevo tiempo estándar'} onCerrar={onCerrar}>
      <div className="formulario">
        {texto('seccion', 'Sección', ambitoFijo)}
        {texto('grupo_hf', 'Grupo HF (opcional)', ambitoFijo)}
        {texto('articulo', 'Artículo (opcional)', ambitoFijo)}
        {texto('tipo_operacion', 'Tipo de operación (opcional)', ambitoFijo)}
      </div>
      <div className="formulario" style={{ marginTop: 8 }}>
        {texto('minutos_preparacion', 'Preparación (min)')}
        {texto('minutos_por_unidad', 'Minutos por unidad')}
        {texto('minutos_por_linea', 'Minutos por línea')}
      </div>
      <label className="campo" style={{ marginTop: 8 }}>
        Origen del dato / notas (p. ej. «cronometrado 12/09 por J. Equipo»)
        <input value={f.notas} onChange={(e) => setF({ ...f, notas: e.target.value })} />
      </label>
      <MensajeError error={err} />
      <div className="botones" style={{ marginTop: 8 }}>
        <button
          className="primario"
          disabled={!f.seccion}
          onClick={async () => {
            try {
              await api.post('/tiempos-estandar', {
                seccion: f.seccion,
                grupo_hf: f.grupo_hf || null,
                articulo: f.articulo || null,
                tipo_operacion: f.tipo_operacion || null,
                minutos_preparacion: Number(f.minutos_preparacion) || 0,
                minutos_por_unidad: Number(f.minutos_por_unidad) || 0,
                minutos_por_linea: Number(f.minutos_por_linea) || 0,
                notas: f.notas || null,
              })
              onHecho()
            } catch (e) {
              setErr(e)
            }
          }}
        >
          Guardar versión
        </button>
        <button onClick={onCerrar}>Cancelar</button>
      </div>
    </Modal>
  )
}

// ------------------------------------------------------------------ parámetros
function ParametrosPlan() {
  const { sesion } = useSesion()
  const { datos, error, recargar } = useDatos(() => api.get<Parametros>('/configuracion'), [])
  const editable = puede(sesion, 'configurar')
  if (error) return <MensajeError error={error} />
  if (!datos) return <Cargando />
  return (
    <>
      <p className="pequeno tenue">Cada parámetro está versionado. Los cambios se aplican en el siguiente cálculo o replanificación del plan.</p>
      {Object.entries(datos).map(([clave, p]) => (
        <EditorParametro key={clave} clave={clave} p={p} editable={editable} onGuardado={recargar} />
      ))}
    </>
  )
}

function esPlano(v: Record<string, unknown>) {
  return Object.values(v).every((x) => typeof x === 'number' || typeof x === 'boolean' || typeof x === 'string')
}

function EditorParametro({ clave, p, editable, onGuardado }: { clave: string; p: Parametros[string]; editable: boolean; onGuardado: () => void }) {
  const plano = esPlano(p.valor)
  const [valores, setValores] = useState<Record<string, unknown>>(p.valor)
  const [json, setJson] = useState(JSON.stringify(p.valor, null, 2))
  const [motivo, setMotivo] = useState('')
  const [err, setErr] = useState<unknown>(null)
  const [ok, setOk] = useState(false)
  const suma = clave === 'pesos_prioridad' ? Object.values(valores).reduce<number>((a, x) => a + (typeof x === 'number' ? x : 0), 0) : null
  const guardar = async () => {
    setErr(null)
    setOk(false)
    try {
      const valor = plano ? valores : (JSON.parse(json) as Record<string, unknown>)
      await api.put(`/configuracion/${clave}`, { valor, motivo: motivo || null })
      setOk(true)
      setMotivo('')
      onGuardado()
    } catch (e) {
      setErr(e instanceof SyntaxError ? new Error(`JSON no válido: ${e.message}`) : e)
    }
  }
  return (
    <section className="panel">
      <h2>
        {clave} <span className="pequeno tenue">v{p.version} {p.es_defecto && '· valores por defecto'}</span>
      </h2>
      <p className="pequeno tenue">{p.descripcion}</p>
      {plano ? (
        <div className="formulario">
          {Object.entries(valores).map(([k, v]) => (
            <label className="campo" key={k}>
              {k}
              {typeof v === 'boolean' ? (
                <input type="checkbox" disabled={!editable} checked={v} onChange={(e) => setValores({ ...valores, [k]: e.target.checked })} />
              ) : (
                <input
                  type={typeof v === 'number' ? 'number' : 'text'}
                  step="any"
                  disabled={!editable}
                  value={String(v)}
                  onChange={(e) => setValores({ ...valores, [k]: typeof v === 'number' ? Number(e.target.value) : e.target.value })}
                />
              )}
            </label>
          ))}
        </div>
      ) : (
        <textarea className="mono" style={{ width: '100%', minHeight: 160 }} value={json} disabled={!editable} onChange={(e) => setJson(e.target.value)} />
      )}
      {suma != null && Math.abs(suma - 1) > 0.001 && <div className="mensaje aviso">Los pesos suman {suma.toFixed(2)}; se normalizan al calcular, pero conviene que sumen 1.</div>}
      {editable && (
        <div className="botones" style={{ marginTop: 8 }}>
          <input placeholder="Motivo del cambio" value={motivo} onChange={(e) => setMotivo(e.target.value)} style={{ minWidth: 260 }} />
          <button className="primario" onClick={guardar}>
            Guardar
          </button>
          {ok && <span className="pequeno">Guardado.</span>}
        </div>
      )}
      <MensajeError error={err} />
    </section>
  )
}

// ------------------------------------------------------------------ integraciones
function Integraciones() {
  const { sesion } = useSesion()
  const maestro = useDatos(() => api.get<Record<string, { maestro: string; respaldo: string }>>('/integraciones/sistema-maestro'), [])
  const [sistema, setSistema] = useState('ortems')
  const [fichero, setFichero] = useState<File | null>(null)
  const [res, setRes] = useState<{ sistema: string; filas: number; actualizadas: number; sin_correspondencia: string[]; conflictos: string[]; errores: string[] } | null>(null)
  const [err, setErr] = useState<unknown>(null)
  return (
    <>
      <section className="panel">
        <h2>Sistema maestro por tipo de dato</h2>
        <p className="pequeno tenue">Cuando dos fuentes discrepan manda el sistema maestro; la discrepancia queda registrada como incidencia de datos con ambos valores.</p>
        {!maestro.datos ? (
          <Cargando />
        ) : (
          <table>
            <thead>
              <tr>
                <th>Dato</th>
                <th>Maestro</th>
                <th>Respaldo</th>
              </tr>
            </thead>
            <tbody>
              {Object.entries(maestro.datos).map(([k, v]) => (
                <tr key={k}>
                  <td>{k}</td>
                  <td>
                    <strong>{v.maestro}</strong>
                  </td>
                  <td className="pequeno">{v.respaldo}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>
      {puede(sesion, 'configurar') && (
        <section className="panel">
          <h2>Importar exportación CSV</h2>
          <p className="pequeno tenue">
            Primera fila con nombres de columna; separador «;», «,» o tabulador. ORTEMS: <span className="mono">of, prioridad, semana</span> · MRP:{' '}
            <span className="mono">of, material_disponible (SI/NO), fecha_material</span> y opcionalmente la ruta <span className="mono">operacion, minutos, secuencia, seccion</span> · Teamcenter:{' '}
            <span className="mono">articulo, revision, descripcion</span> (el resto de columnas se guarda como datos técnicos).
          </p>
          <div className="botones">
            <select value={sistema} onChange={(e) => setSistema(e.target.value)}>
              <option value="ortems">ORTEMS</option>
              <option value="mrp">MRP</option>
              <option value="teamcenter">Teamcenter</option>
            </select>
            <input type="file" accept=".csv,.txt" onChange={(e) => setFichero(e.target.files?.[0] ?? null)} />
            <button
              className="primario"
              disabled={!fichero}
              onClick={async () => {
                setErr(null)
                setRes(null)
                try {
                  setRes(await api.subir(`/integraciones/${sistema}/importar`, fichero!))
                } catch (e) {
                  setErr(e)
                }
              }}
            >
              Importar
            </button>
          </div>
          <MensajeError error={err} />
          {res && (
            <div style={{ marginTop: 10 }}>
              <div className="mensaje ok">
                {res.sistema}: {res.filas} filas leídas, {res.actualizadas} OF actualizadas.
              </div>
              {[
                ['Sin correspondencia', res.sin_correspondencia],
                ['Conflictos entre fuentes', res.conflictos],
                ['Errores', res.errores],
              ].map(
                ([t, xs]) =>
                  (xs as string[]).length > 0 && (
                    <details key={t as string} open>
                      <summary>
                        {t as string} ({(xs as string[]).length})
                      </summary>
                      <ul className="pequeno">
                        {(xs as string[]).map((x, i) => (
                          <li key={i}>{x}</li>
                        ))}
                      </ul>
                    </details>
                  ),
              )}
            </div>
          )}
        </section>
      )}
    </>
  )
}

// ------------------------------------------------------------------ aprendizaje
interface Propuesta {
  id: number
  estado: string
  muestras: number
  ratio: number
  actual: number
  propuesto: number
  explicacion: string
  creada: string
  decidida_por: string | null
  ambito: { seccion: string; grupo_hf: string | null; tipo_operacion: string | null } | null
}

function Aprendizaje() {
  const { sesion } = useSesion()
  const { datos, error, recargar } = useDatos(() => api.get<Propuesta[]>('/aprendizaje/propuestas'), [])
  const [err, setErr] = useState<unknown>(null)
  const [msg, setMsg] = useState<string | null>(null)
  const aprobar = puede(sesion, 'aprobar_estimaciones')
  return (
    <section className="panel">
      <div className="cabecera">
        <div>
          <h2>Aprendizaje de tiempos</h2>
          <p className="pequeno tenue">
            El sistema compara el tiempo real fichado con el planificado y PROPONE ajustes. Nada se aplica sin aprobación; toda aprobación crea una versión nueva del tiempo estándar que se puede revertir.
          </p>
        </div>
        {aprobar && (
          <button
            className="primario"
            onClick={async () => {
              setErr(null)
              try {
                const r = await api.post<unknown[]>('/aprendizaje/proponer')
                setMsg(r.length ? `${r.length} propuestas nuevas` : 'No hay desviaciones suficientes para proponer cambios (faltan muestras o la desviación es pequeña).')
                recargar()
              } catch (e) {
                setErr(e)
              }
            }}
          >
            Analizar fichajes
          </button>
        )}
      </div>
      {msg && <div className="mensaje ok">{msg}</div>}
      <MensajeError error={error ?? err} />
      {!datos ? (
        <Cargando />
      ) : datos.length === 0 ? (
        <p className="tenue">Sin propuestas.</p>
      ) : (
        <table>
          <thead>
            <tr>
              <th>Ámbito</th>
              <th>Muestras</th>
              <th>Real / plan</th>
              <th>min/ud actual → propuesto</th>
              <th>Explicación</th>
              <th>Estado</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {datos.map((p) => (
              <tr key={p.id}>
                <td className="pequeno">{p.ambito ? `${p.ambito.seccion} / ${p.ambito.grupo_hf ?? '—'} / ${p.ambito.tipo_operacion ?? '—'}` : '—'}</td>
                <td>{p.muestras}</td>
                <td>×{p.ratio.toFixed(2)}</td>
                <td>
                  {p.actual} → <strong>{p.propuesto}</strong>
                </td>
                <td className="pequeno">{p.explicacion}</td>
                <td>
                  <span className="etiqueta">{p.estado}</span>
                  {p.decidida_por && <div className="pequeno tenue">por {p.decidida_por}</div>}
                </td>
                <td>
                  {aprobar && p.estado === 'PROPUESTA' && (
                    <div className="botones">
                      {[true, false].map((a) => (
                        <button
                          key={String(a)}
                          className={a ? 'primario' : ''}
                          onClick={async () => {
                            setErr(null)
                            try {
                              await api.post(`/aprendizaje/propuestas/${p.id}/decidir`, { aprobar: a })
                              setMsg(a ? 'Aprobada: nueva versión del tiempo estándar creada y OF pendientes recalculadas.' : 'Propuesta rechazada.')
                              recargar()
                            } catch (e) {
                              setErr(e)
                            }
                          }}
                        >
                          {a ? 'Aprobar' : 'Rechazar'}
                        </button>
                      ))}
                    </div>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </section>
  )
}
