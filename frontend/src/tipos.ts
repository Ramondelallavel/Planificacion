export type Nivel = 'VERDE' | 'AMARILLO' | 'NARANJA' | 'ROJO'

export interface Kpis {
  operaciones: number
  planificadas: number
  no_planificadas: number
  provisionales: number
  horas_planificadas: number
  fin_plan: string | null
  cumplimiento_semana: number | null
  aparatos_evaluados: number
  aparatos_en_plazo: number
  retraso_total_h: number
  cambios_setup: number
  horas_muertas: number
  wip_medio_of: number
  utilizacion_media: number
  recursos_criticos: string[]
  tandas_en_riesgo: number
}

export interface RiesgoTanda {
  tanda_id: number
  numero: string
  semana: string | null
  nivel: Nivel
  motivos: string[]
  aparatos: number
  aparatos_en_riesgo: number
  horas_restantes: number
  fin_previsto: string | null
  progreso: number
}

export interface RiesgoAparato {
  aparato_id: number
  referencia: string
  tanda_id: number
  nivel: Nivel
  motivos: string[]
  fin_previsto: string | null
  holgura_h: number | null
  horas_restantes: number
  semana: string | null
  limite: string | null
  ofs_pendientes: number
  ofs_no_planificables: number
  acciones: string[]
}

export interface Cuello {
  recurso_id: number
  codigo: string
  nombre: string
  seccion: string | null
  demanda_h: number
  capacidad_h: number
  utilizacion: number
  cola: number
  saturado_h: number
  nivel: Nivel
  mensaje: string | null
}

export interface Comprobacion {
  paso: string
  estado: 'OK' | 'AVISO' | 'BLOQUEANTE'
  detalle: string
}

export interface Factor {
  factor: string
  nombre: string
  valor: number
  peso: number
  contribucion: number
}

export interface Explicacion {
  prioridad: {
    valor: number
    factores: Factor[]
    motivos: string[]
    holgura_h: number | null
    cadena_pendiente_h: number
    limite: string | null
    datos_no_disponibles: string[]
  } | null
  inicio_condicionado_por: string[]
  recurso: { codigo: string; motivo: string }
  operario: { codigo: string; nombre: string; motivo: string } | null
  alternativas: { recurso: string; operario: string | null; fin: string }[]
  setup: string | null
  provisional: string | null
  cuello_botella: boolean
  cambio_manual?: { usuario: string; motivo: string; fecha: string }
}

export interface Asignacion {
  operacion_id: number
  of_id: number
  of: string
  tipo: string
  seccion: string | null
  grupo_hf: string | null
  recurso_id: number | null
  recurso: string | null
  unidad: number
  operario_id: number | null
  operario: string | null
  operario_codigo: string | null
  inicio: string
  fin: string
  tramos: [string, string][] | null
  minutos: number
  prioridad: number | null
  bloqueada: boolean
  provisional: boolean
  riesgo: Nivel
  aparato: string | null
  aparato_id: number | null
  tanda: string | null
  tanda_id: number | null
  estado_op: string
  urgente: boolean
  familia: string | null
  explicacion?: Explicacion
}

export interface RecursoGantt {
  id: number
  codigo: string
  nombre: string
  seccion: string | null
  tipo: string
  estado: string
  capacidad: number
}

export interface Cambio {
  fecha: string
  tipo: string
  of: string | null
  operacion_id?: number
  antes: { inicio: string; fin: string; recurso: string | null; operario: string | null } | null
  despues: { inicio: string; fin: string; recurso: string | null; operario: string | null } | null
  impacto_min: number | null
  motivo: string | null
  usuario?: string | null
  riesgo_antes?: Nivel | null
  riesgo_despues?: Nivel | null
}

export interface NoPlanificada {
  operacion_id: number
  of_id: number
  of: string
  tipo: string
  motivo: string
  detalle: string
}

export interface ResultadoReplan {
  resumen: string
  cambios: Cambio[]
  tandas: { tanda: string; riesgo_antes: Nivel | null; riesgo_despues: Nivel; fin_antes: string | null; fin_despues: string | null; motivos: string[] }[]
  afectadas: number
  sale_del_plan: NoPlanificada[]
}

export interface OFResumen {
  id: number
  numero: string
  seccion: string | null
  grupo_hf: string | null
  descripcion: string | null
  modo: string | null
  semana: string | null
  estado: string
  estado_programacion: string
  programa: string | null
  horas_estimadas: number | null
  horas_reales: number | null
  riesgo: Nivel
  urgente: boolean
  bloqueada: boolean
  tiene_hoja: boolean
  aparato_id: number | null
  tanda_id: number | null
  inicio_previsto: string | null
  fin_previsto: string | null
  material_disponible: boolean | null
  disponible_prevista: string | null
  prioridad_ortems: number | null
  paginas: number[] | null
}

export interface Recurso {
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
