import { useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { api, puede } from '../api'
import { useSesion } from '../App'
import Markdown from '../componentes/Markdown'
import { capacidad } from '../plataforma'

// Asistente: preguntas en lenguaje natural sobre el plan, respondidas por Claude con los
// datos reales de la aplicación. Claude solo CONSULTA (y simula sobre una copia): el plan
// oficial lo siguen decidiendo las personas desde sus pantallas.

type Turno = { role: 'user' | 'assistant'; content: string }
interface Herramienta {
  name: string
  description: string
  inputSchema?: { type: 'object'; properties?: Record<string, unknown>; required?: string[] }
  execute(input: Record<string, unknown>, ctx: { signal: AbortSignal }): unknown
}
interface OpcionesSample {
  onText?: (u: { text: string; delta: string }) => void
  signal?: AbortSignal
  tools?: Herramienta[]
  modelTier?: 'default' | 'complex' | 'quick'
  cache?: boolean
}
interface Sample {
  (input: string | Turno[], o?: OpcionesSample): Promise<{ text: string; truncated: boolean }>
  limits(): Promise<{ tools?: { maxCount: number } }>
}
interface ErrorSample {
  code?: string
  text?: string
}

// eslint-disable-next-line @typescript-eslint/no-explicit-any
type Cualquiera = any

const SUGERENCIAS = [
  '¿Cómo está la fábrica ahora mismo? Resúmelo para la reunión de las 8.',
  '¿Qué tanda corre más riesgo de no llegar a su semana y qué haría para salvarla?',
  '¿Qué máquinas son cuello de botella los próximos días?',
  '¿Qué pasa si la máquina más cargada se avería 8 horas?',
  '¿Compensa un turno extra el sábado? Simúlalo.',
  '¿Qué operaciones se están desviando más de su tiempo previsto?',
  '¿Qué equipo está más cargado y cuánta gente le haría falta?',
]

const ERRORES: Record<string, string> = {
  not_granted: 'No se ha dado permiso para usar Claude en esta página.',
  sampling_disabled: 'Claude no está disponible para esta cuenta u organización.',
  not_declared: 'Esta versión de la página no tiene activado el asistente.',
  capability_disabled: 'El asistente no está disponible en esta vista.',
  rate_limited: 'Demasiadas preguntas seguidas o límite de uso alcanzado. Prueba dentro de un rato.',
  session_expired: 'La sesión de claude.ai ha caducado: vuelve a entrar.',
  refused: 'Claude no ha querido responder a esa pregunta. Prueba a formularla de otra manera.',
  empty_completion: 'La respuesta ha llegado vacía. Prueba a preguntar algo más concreto.',
  prompt_too_large: 'La conversación es demasiado larga. Empieza una nueva.',
  tools_unavailable: 'Esta vista no permite que Claude consulte los datos.',
}
const PERMANENTES = new Set(['not_granted', 'sampling_disabled', 'not_declared', 'capability_disabled'])

const pct = (v: number | null | undefined) => (v == null ? null : `${Math.round(v * 100)}%`)
const dia = (iso: string) => new Date(iso + 'T12:00:00').toLocaleDateString('es-ES', { weekday: 'short', day: 'numeric', month: 'numeric' })

async function recursosPorCodigo() {
  const rs = await api.get<{ id: number; codigo: string; nombre: string; seccion: string | null; estado: string; capacidad: number }[]>('/recursos')
  return rs
}
async function idDeOF(numero: string) {
  const r = await api.get<{ items: { id: number; numero: string }[] }>(`/ofs?q=${encodeURIComponent(numero)}&limite=10`)
  const of = r.items.find((o) => o.numero === numero) ?? r.items[0]
  if (!of) throw new Error(`No existe la OF ${numero}`)
  return of.id
}

function herramientas(puedeSimular: boolean, informar: (t: string) => void): Herramienta[] {
  const lista: Herramienta[] = [
    {
      name: 'estado_fabrica',
      description:
        'Foto actual de la fábrica: indicadores del plan activo, tandas y aparatos en riesgo con sus motivos, cuellos de botella, máquinas paradas, OF retrasadas, acciones recomendadas y personal. Úsala primero para casi cualquier pregunta general.',
      async execute() {
        informar('Consultando el estado de la fábrica…')
        const ct = await api.get<Cualquiera>('/dashboard/control-tower')
        return {
          ahora: ct.ahora,
          plan: ct.plan && { nombre: ct.plan.nombre, creado: ct.plan.creado, definitivo: ct.plan.definitivo, kpis: ct.plan.kpis },
          resumen: ct.resumen,
          alertas_por_tanda: (ct.alertas ?? []).slice(0, 8).map((a: Cualquiera) => ({
            tanda: a.tanda,
            semana: a.semana,
            nivel: a.nivel,
            titulo: a.titulo,
            fin_previsto: a.fin_previsto,
            detalles: (a.detalles ?? []).slice(0, 5).map((d: Cualquiera) => d.texto),
          })),
          aparatos_en_riesgo: (ct.aparatos ?? [])
            .filter((a: Cualquiera) => a.nivel !== 'VERDE')
            .slice(0, 15)
            .map((a: Cualquiera) => ({ referencia: a.referencia, nivel: a.nivel, fin_previsto: a.fin_previsto, motivos: (a.motivos ?? []).slice(0, 2) })),
          cuellos_de_botella: ct.cuellos,
          maquinas_paradas: ct.maquinas_paradas,
          of_retrasadas: (ct.retrasadas ?? []).slice(0, 15).map((r: Cualquiera) => ({ of: r.of, tipo: r.tipo, motivo: r.motivo })),
          acciones_recomendadas: (ct.acciones_recomendadas ?? []).map((a: Cualquiera) => a.texto),
          personal: ct.personal,
        }
      },
    },
    {
      name: 'buscar',
      description: 'Busca por texto OF, tandas, aparatos, artículos, máquinas y operarios. Devuelve tipo, título y un detalle breve de cada coincidencia.',
      inputSchema: { type: 'object', properties: { texto: { type: 'string', description: 'número de OF, tanda, aparato, código de máquina, nombre…' } }, required: ['texto'] },
      async execute(input) {
        informar(`Buscando «${String(input.texto ?? '')}»…`)
        const r = await api.get<{ tipo: string; titulo: string; sub: string | null }[]>(`/buscar?q=${encodeURIComponent(String(input.texto ?? ''))}&limite=15`)
        return r.map((x) => ({ tipo: x.tipo, titulo: x.titulo, detalle: x.sub }))
      },
    },
    {
      name: 'detalle_of',
      description: 'Detalle de una orden de fabricación por su número: estado, riesgo, fechas previstas, operaciones con su planificación o el motivo por el que no se pueden planificar, dependencias y aparatos.',
      inputSchema: { type: 'object', properties: { numero: { type: 'string', description: 'número de la OF' } }, required: ['numero'] },
      async execute(input) {
        const numero = String(input.numero ?? '').trim()
        informar(`Leyendo la OF ${numero}…`)
        const o = await api.get<Cualquiera>(`/ofs/${await idDeOF(numero)}`)
        return {
          numero: o.numero,
          descripcion: o.descripcion,
          seccion: o.seccion,
          semana: o.semana,
          estado: o.estado,
          estado_programacion: o.estado_programacion,
          riesgo: o.riesgo,
          riesgo_detalle: o.riesgo_detalle,
          urgente: o.urgente,
          bloqueada: o.bloqueada,
          material_disponible: o.material_disponible,
          inicio_previsto: o.inicio_previsto,
          fin_previsto: o.fin_previsto,
          horas_estimadas: o.horas_estimadas,
          aparatos: (o.aparatos ?? []).map((a: Cualquiera) => a.referencia),
          operaciones: (o.operaciones ?? []).map((op: Cualquiera) => ({
            tipo: op.tipo,
            seccion: op.seccion,
            estado: op.estado,
            minutos: op.duracion_estimada_min,
            plan: op.plan ? { inicio: op.plan.inicio, fin: op.plan.fin, maquina: op.plan.recurso, provisional: op.plan.provisional } : null,
            no_planificable: op.no_planificada ? { motivo: op.no_planificada.motivo, detalle: op.no_planificada.detalle } : null,
          })),
          predecesoras: (o.predecesoras ?? []).map((p: Cualquiera) => `${p.numero} (${p.estado ?? '?'})`),
          sucesoras: (o.sucesoras ?? []).map((p: Cualquiera) => `${p.numero} (${p.estado ?? '?'})`),
          incidencias_de_datos: (o.incidencias_datos ?? []).filter((i: Cualquiera) => i.estado === 'ABIERTA').map((i: Cualquiera) => `${i.severidad}: ${i.mensaje}`),
        }
      },
    },
    {
      name: 'capacidad',
      description:
        'Ocupación planificada frente a capacidad disponible (turnos, jornadas extra, festivos y paradas) por sección y por día, y las máquinas más cargadas. Porcentajes de ocupación; «sin turno» si ese día no se trabaja.',
      inputSchema: { type: 'object', properties: { dias: { type: 'number', description: 'días a mirar desde hoy (7–21, por defecto 10)' } } },
      async execute(input) {
        informar('Mirando la carga de las máquinas…')
        const dias = Math.min(21, Math.max(3, Number(input.dias) || 10))
        const c = await api.get<Cualquiera>(`/plan/activo/capacidad?dias=${dias}`)
        const celda = (x: { disponible: number; ocupado: number }) => (x.disponible ? pct(x.ocupado / x.disponible) : x.ocupado ? 'sobrecarga sin turno' : 'sin turno')
        const maquinas = (c.recursos ?? [])
          .map((r: Cualquiera) => {
            const disp = r.celdas.reduce((n: number, x: Cualquiera) => n + x.disponible, 0)
            const oc = r.celdas.reduce((n: number, x: Cualquiera) => n + x.ocupado, 0)
            return { maquina: r.codigo, seccion: r.seccion, estado: r.estado, ocupacion_periodo: disp ? oc / disp : 0, horas_planificadas: Math.round(oc / 6) / 10, por_dia: r.celdas.map(celda) }
          })
          .filter((m: Cualquiera) => m.horas_planificadas > 0)
          .sort((a: Cualquiera, b: Cualquiera) => b.ocupacion_periodo - a.ocupacion_periodo)
          .slice(0, 10)
          .map((m: Cualquiera) => ({ ...m, ocupacion_periodo: pct(m.ocupacion_periodo) }))
        return {
          dias: (c.dias ?? []).map(dia),
          por_seccion: (c.secciones ?? []).map((s: Cualquiera) => ({ seccion: s.seccion, por_dia: s.celdas.map(celda) })),
          maquinas_mas_cargadas: maquinas,
        }
      },
    },
    {
      name: 'seguimiento',
      description:
        'Plan frente a real con los fichajes de planta: adherencia al plan, operaciones que debían estar terminadas y no lo están, trabajos en curso (y si exceden su tiempo) y desviaciones de tiempo real frente a previsto por sección y operación.',
      async execute() {
        informar('Comparando el plan con los fichajes…')
        const d = await api.get<Cualquiera>('/dashboard/seguimiento?dias=14')
        return {
          adherencia: { debidas: d.adherencia.debidas, terminadas: d.adherencia.terminadas, pct: pct(d.adherencia.pct), pendientes: d.adherencia.pendientes.slice(0, 10) },
          en_curso: d.en_curso.map((e: Cualquiera) => ({ operario: e.operario, of: e.of, operacion: e.operacion, maquina: e.recurso, estado: e.estado, llevado_min: e.trabajado_min, previsto_min: e.previsto_min, excede: e.excede })),
          resumen_14_dias: d.resumen,
          desviacion_por_tipo: d.por_tipo.slice(0, 12),
          mayores_desviaciones: d.mayores_desviaciones.slice(0, 5),
        }
      },
    },
    {
      name: 'maquinas_y_turnos',
      description: 'Lista de máquinas (código, sección, estado, capacidad), turnos de trabajo con su horario, y jornadas extra y festivos próximos del calendario.',
      async execute() {
        informar('Leyendo máquinas y calendario…')
        const [rs, ts, cal] = await Promise.all([recursosPorCodigo(), api.get<Cualquiera[]>('/turnos'), api.get<Cualquiera>('/calendario')])
        return {
          maquinas: rs.map((r) => ({ codigo: r.codigo, nombre: r.nombre, seccion: r.seccion, estado: r.estado, capacidad: r.capacidad })),
          turnos: ts.filter((t) => t.activo).map((t) => ({ codigo: t.codigo, nombre: t.nombre, horario: `${t.hora_inicio}–${t.hora_fin}`, dias: t.dias_semana })),
          jornadas_extra: cal.jornadas_extra,
          festivos: cal.festivos,
        }
      },
    },
    {
      name: 'carga_equipos',
      description:
        'Carga de trabajo de cada equipo (sección): horas pendientes frente a capacidad de máquinas y personas en los próximos días, porcentaje de carga, rendimiento configurado, número de operarios y máquinas, y de qué tandas y tipos de operación viene el trabajo.',
      inputSchema: { type: 'object', properties: { dias: { type: 'number', description: '7, 14 o 21 (por defecto 14)' } } },
      async execute(input) {
        informar('Mirando la carga de cada equipo…')
        const d = await api.get<Cualquiera>(`/carga?dias=${[7, 14, 21].includes(Number(input.dias)) ? Number(input.dias) : 14}`)
        return {
          hasta: d.hasta,
          equipos: d.secciones.map((e: Cualquiera) => ({
            seccion: e.seccion,
            pendiente_h: e.demanda_h,
            capacidad_h: e.capacidad_h,
            capacidad_maquinas_h: e.capacidad_maquinas_h,
            capacidad_personas_h: e.capacidad_personas_h,
            carga: pct(e.carga),
            limitada_por: e.limitada_por,
            rendimiento_pct: e.rendimiento,
            operarios: e.operarios.length,
            maquinas: e.maquinas.map((m: Cualquiera) => m.codigo),
            sin_tiempo: e.sin_tiempo,
            por_tanda: e.por_tanda.slice(0, 5),
            por_tipo: e.por_tipo.slice(0, 5),
          })),
        }
      },
    },
    {
      name: 'materiales',
      description:
        'Materiales que consumen las OF abiertas frente a stock y entradas previstas: materiales con falta, OF bloqueadas por material o esperando una entrada. Solo cuentan los materiales controlados (con stock registrado).',
      async execute() {
        informar('Revisando materiales…')
        const d = await api.get<Cualquiera>('/materiales')
        const importantes = d.materiales.filter((m: Cualquiera) => m.controlado || m.ofs_falta).sort((a: Cualquiera, b: Cualquiera) => (a.balance ?? 0) - (b.balance ?? 0))
        return {
          resumen: d.resumen,
          controlados: importantes.slice(0, 25).map((m: Cualquiera) => ({
            codigo: m.codigo,
            descripcion: m.descripcion,
            unidad: m.unidad,
            necesidad: m.necesidad,
            stock: m.stock,
            entradas: m.entradas.map((e: Cualquiera) => `${e.cantidad} el ${e.fecha.slice(0, 10)}`),
            balance: m.balance,
            ofs_sin_material: m.ofs_falta,
            ofs_esperan: m.ofs_esperan,
          })),
          sin_controlar: d.materiales.filter((m: Cualquiera) => !m.controlado).length,
        }
      },
    },
  ]
  if (puedeSimular)
    lista.push({
      name: 'simular',
      description:
        'Simula un escenario sobre una COPIA del plan (nunca cambia el plan real) y devuelve indicadores actuales frente a simulados, riesgo de tandas y aparatos, y OF que cambian. La simulación queda guardada para compararla en Simulación → Comparar simulaciones. Combina en una llamada todo lo que quieras probar a la vez.',
      inputSchema: {
        type: 'object',
        properties: {
          nombre: { type: 'string', description: 'título corto del escenario' },
          averias: { type: 'array', items: { type: 'object', properties: { maquina: { type: 'string' }, horas: { type: 'number' }, inicio: { type: 'string', description: 'ISO local; por defecto ahora' } }, required: ['maquina'] } },
          faltan_operarios: { type: 'array', items: { type: 'object', properties: { seccion: { type: 'string' }, cantidad: { type: 'number' } }, required: ['seccion'] } },
          turnos_extra: {
            type: 'array',
            items: { type: 'object', properties: { fecha: { type: 'string', description: 'AAAA-MM-DD' }, turno: { type: 'string', description: 'código de turno' }, secciones: { type: 'array', items: { type: 'string' } } }, required: ['fecha', 'turno'] },
          },
          maquinas_extra: { type: 'array', items: { type: 'object', properties: { maquina: { type: 'string', description: 'máquina a duplicar' }, cantidad: { type: 'number' } }, required: ['maquina'] } },
          adelantar_of: { type: 'array', items: { type: 'string' }, description: 'números de OF a marcar urgentes' },
        },
      },
      async execute(input) {
        informar('Simulando el escenario…')
        const rs = await recursosPorCodigo()
        const rec = (codigo: unknown) => {
          const c = String(codigo ?? '').trim().toUpperCase()
          const r = rs.find((x) => x.codigo.toUpperCase() === c) ?? rs.find((x) => x.codigo.toUpperCase().includes(c))
          if (!r) throw new Error(`No existe la máquina ${String(codigo)}. Máquinas: ${rs.map((x) => x.codigo).join(', ')}`)
          return r.id
        }
        const lista = (v: unknown) => (Array.isArray(v) ? (v as Record<string, unknown>[]) : [])
        const esc: Record<string, unknown> = { modo: 'completo', nombre: `Asistente: ${String(input.nombre ?? 'escenario')}`.slice(0, 120) }
        if (lista(input.averias).length) esc.averias = lista(input.averias).map((a) => ({ recurso_id: rec(a.maquina), horas: Number(a.horas) || 8, inicio: a.inicio ? String(a.inicio) : undefined }))
        if (lista(input.faltan_operarios).length) esc.faltan_operarios = lista(input.faltan_operarios).map((f) => ({ seccion: String(f.seccion), cantidad: Number(f.cantidad) || 1 }))
        if (lista(input.turnos_extra).length)
          esc.turnos_extra = lista(input.turnos_extra).map((t) => ({ fecha: String(t.fecha), turno: String(t.turno), secciones: Array.isArray(t.secciones) && t.secciones.length ? t.secciones.map(String) : null }))
        if (lista(input.maquinas_extra).length) esc.recursos_extra = lista(input.maquinas_extra).map((m) => ({ clonar_recurso_id: rec(m.maquina), cantidad: Number(m.cantidad) || 1 }))
        if (Array.isArray(input.adelantar_of) && input.adelantar_of.length) esc.adelantar_of = await Promise.all(input.adelantar_of.map((n) => idDeOF(String(n))))
        const r = await api.post<Cualquiera>('/plan/simulaciones/escenario', { escenario: esc, guardar: true })
        const k = (x: Cualquiera) => ({
          planificadas: x.planificadas,
          no_planificables: x.no_planificadas,
          fin_plan: x.fin_plan,
          cumplimiento_semana: pct(x.cumplimiento_semana),
          aparatos_en_plazo: `${x.aparatos_en_plazo}/${x.aparatos_evaluados}`,
          retraso_total_h: x.retraso_total_h,
          recursos_criticos: x.recursos_criticos,
        })
        return {
          simulacion_id: r.simulacion_id,
          escenario: r.escenario,
          indicadores_actual: k(r.kpis_base),
          indicadores_simulado: k(r.kpis_simulado),
          tandas: r.tandas,
          aparatos_que_cambian_de_riesgo: r.aparatos.filter((a: Cualquiera) => a.riesgo_base !== a.riesgo_simulado).slice(0, 15),
          of_que_cambian: r.cambios.length,
          mayores_cambios: [...r.cambios].sort((a: Cualquiera, b: Cualquiera) => Math.abs(b.impacto_min ?? 0) - Math.abs(a.impacto_min ?? 0)).slice(0, 8),
          operaciones_que_salen_del_plan: r.operaciones_que_salen_del_plan.slice(0, 8),
        }
      },
    })
  return lista
}

export default function Asistente() {
  const { sesion } = useSesion()
  const [sample, setSample] = useState<Sample | null | undefined>(undefined)
  const [conHerramientas, setConHerramientas] = useState(true)
  const [turnos, setTurnos] = useState<Turno[]>([])
  const [pregunta, setPregunta] = useState('')
  const [respuesta, setRespuesta] = useState<string | null>(null)
  const [actividad, setActividad] = useState<string[]>([])
  const [aviso, setAviso] = useState<string | null>(null)
  const [bloqueado, setBloqueado] = useState(false)
  const [detallado, setDetallado] = useState(true)
  const control = useRef<AbortController | null>(null)
  const fin = useRef<HTMLDivElement>(null)

  useEffect(() => {
    let vivo = true
    capacidad<Sample>('sample').then(async (s) => {
      if (!vivo) return
      setSample(() => s) // es una función: con setSample(s) React la llamaría como actualizador
      if (s) {
        const l = await s.limits().catch(() => null)
        if (vivo) setConHerramientas(!!l?.tools)
      }
    })
    return () => {
      vivo = false
      control.current?.abort()
    }
  }, [])
  useEffect(() => fin.current?.scrollIntoView({ block: 'end', behavior: 'smooth' }), [turnos, respuesta, actividad])

  if (sample === undefined) return <div className="tenue">Conectando con Claude…</div>

  const ocupado = respuesta !== null
  const preguntar = async (texto: string) => {
    if (!sample || !texto.trim() || ocupado) return
    setAviso(null)
    setActividad([])
    const nuevos: Turno[] = [...turnos, { role: 'user', content: texto.trim() }]
    setTurnos(nuevos)
    setPregunta('')
    setRespuesta('')
    const ctl = new AbortController()
    control.current = ctl
    try {
      const [ts, secs] = await Promise.all([api.get<Cualquiera[]>('/turnos'), api.get<Cualquiera[]>('/secciones')])
      let contexto = ''
      if (!conHerramientas) {
        // sin herramientas: se le da la foto de la fábrica en el propio mensaje
        const foto = await herramientas(false, () => {})[0].execute({}, { signal: ctl.signal })
        contexto = `\n\nDatos actuales de la fábrica (JSON):\n${JSON.stringify(foto).slice(0, 30000)}`
      }
      const instrucciones =
        `Eres el asistente de planificación de la fábrica HIDRAL (calderería: tandas de fabricación con aparatos y órdenes de fabricación, OF, que pasan por secciones y máquinas). ` +
        `Estás dentro de su aplicación de planificación y control de producción. Respondes en español de España, breve y al grano, a ${sesion?.nombre ?? 'un usuario'} (${sesion?.rol ?? ''}). ` +
        (conHerramientas
          ? 'Usa SIEMPRE las herramientas para obtener los datos reales antes de afirmar nada: no inventes OF, máquinas, cifras ni fechas. Si un dato no está, dilo. '
          : 'Responde solo con los datos que se te dan; no inventes nada. ') +
        'Las simulaciones trabajan sobre una copia: el plan real solo cambia cuando un responsable lo aplica desde Simulación («Aplicar y replanificar») o registra una incidencia. ' +
        'Cuando recomiendes algo, di qué pantalla usar (Control Tower, Plan · Gantt, Capacidad, Carga de trabajo, Materiales, Seguimiento, Incidencias, Simulación, Tandas, Configuración → Calendario). ' +
        'Formato: Markdown sencillo, párrafos cortos, listas y negritas; una tabla pequeña solo si ayuda. Fechas en formato dd/mm y horas hh:mm.\n\n' +
        `Ahora: ${new Date().toLocaleString('es-ES', { weekday: 'long', day: 'numeric', month: 'long', year: 'numeric', hour: '2-digit', minute: '2-digit' })}.\n` +
        `Turnos: ${ts
          .filter((t) => t.activo)
          .map((t) => `${t.codigo} (${t.nombre}, ${t.hora_inicio}–${t.hora_fin})`)
          .join('; ')}.\n` +
        `Secciones: ${secs.map((s) => s.codigo).join(', ')}.` +
        contexto
      // la conversación la guarda la página: instrucciones + últimos turnos
      const entrada: Turno[] = [{ role: 'user', content: instrucciones }, ...nuevos.slice(-12)]
      const r = await sample(entrada, {
        signal: ctl.signal,
        cache: false,
        modelTier: detallado ? 'default' : 'quick',
        tools: conHerramientas ? herramientas(!!sesion && puede(sesion, 'simular'), (t) => setActividad((a) => [...a, t])) : undefined,
        onText: ({ text }) => setRespuesta(text),
      })
      setTurnos([...nuevos, { role: 'assistant', content: r.text + (r.truncated ? '\n\n*(Respuesta cortada: pregunta algo más concreto para verla entera.)*' : '') }])
    } catch (e) {
      const err = e as ErrorSample
      if (err.text) setTurnos([...nuevos, { role: 'assistant', content: err.text + '\n\n*(interrumpida)*' }])
      if (err.code !== 'cancelled')
        setAviso(ERRORES[err.code ?? ''] ?? (e instanceof Error ? `No se ha podido obtener respuesta: ${e.message}` : 'No se ha podido obtener respuesta. Inténtalo de nuevo.'))
      if (err.code && PERMANENTES.has(err.code)) setBloqueado(true)
      if (err.code === 'tools_unavailable') setConHerramientas(false)
    } finally {
      setRespuesta(null)
      setActividad([])
      control.current = null
    }
  }

  return (
    <>
      <div className="cabecera">
        <div>
          <h1>Asistente</h1>
          <div className="sub">
            Pregunta en lenguaje normal. Claude consulta los datos reales de la aplicación (y puede simular escenarios sobre una copia) pero nunca cambia el plan: las decisiones las
            sigues tomando tú.
          </div>
        </div>
        <div className="botones">
          <label className="pequeno">
            <input type="checkbox" checked={detallado} onChange={(e) => setDetallado(e.target.checked)} /> Respuesta razonada (más lenta)
          </label>
          <button
            disabled={!turnos.length || ocupado}
            onClick={() => {
              setTurnos([])
              setAviso(null)
            }}
          >
            Nueva conversación
          </button>
        </div>
      </div>

      {!sample ? (
        <div className="mensaje aviso">
          El asistente solo está disponible cuando la aplicación se abre como página de claude.ai. Todo lo demás funciona igual sin él.
        </div>
      ) : (
        <section className="panel chat">
          {turnos.length === 0 && !ocupado && (
            <div className="sugerencias">
              <p className="tenue">Algunas ideas:</p>
              {SUGERENCIAS.map((s) => (
                <button key={s} className="sugerencia" disabled={bloqueado} onClick={() => preguntar(s)}>
                  {s}
                </button>
              ))}
              {!conHerramientas && <p className="pequeno tenue">En esta vista Claude no puede consultar datos por su cuenta: se le envía un resumen del estado actual con cada pregunta.</p>}
            </div>
          )}
          {turnos.map((t, i) => (
            <div key={i} className={`burbuja ${t.role === 'user' ? 'usuario' : 'claude'}`}>
              {t.role === 'user' ? t.content : <Markdown texto={t.content} />}
            </div>
          ))}
          {ocupado && (
            <div className="burbuja claude">
              {respuesta ? <Markdown texto={respuesta} /> : <span className="tenue">Pensando…</span>}
              {actividad.length > 0 && (
                <ul className="actividad pequeno tenue">
                  {actividad.map((a, i) => (
                    <li key={i}>{a}</li>
                  ))}
                </ul>
              )}
            </div>
          )}
          {aviso && <div className="mensaje error">{aviso}</div>}
          <div ref={fin} />
          <form
            className="entrada-chat"
            onSubmit={(e) => {
              e.preventDefault()
              preguntar(pregunta)
            }}
          >
            <textarea
              id="pregunta-asistente"
              rows={2}
              value={pregunta}
              disabled={bloqueado}
              placeholder="Por ejemplo: ¿qué pasa si la plegadora se avería mañana 6 horas? (Intro para enviar, Mayús+Intro para salto de línea)"
              onChange={(e) => setPregunta(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter' && !e.shiftKey) {
                  e.preventDefault()
                  preguntar(pregunta)
                }
              }}
            />
            {ocupado ? (
              <button type="button" onClick={() => control.current?.abort()}>
                Parar
              </button>
            ) : (
              <button type="submit" className="primario" disabled={!pregunta.trim() || bloqueado}>
                Preguntar
              </button>
            )}
          </form>
          <p className="pequeno tenue">
            Cada pregunta usa tu cuenta de Claude. Las simulaciones que haga quedan en <Link to="/simulacion">Simulación → Comparar simulaciones</Link>.
          </p>
        </section>
      )}
    </>
  )
}
