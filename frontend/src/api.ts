// Cliente de la API REST. El token se guarda en sessionStorage (se pierde al cerrar la pestaña).
// En la edición «navegador» la API no está en un servidor: las peticiones van al motor local.

import { NAVEGADOR, pedirMotor } from './motor'

export class ErrorApi extends Error {
  estado: number
  errores: string[]
  datos: unknown
  constructor(estado: number, mensaje: string, errores: string[] = [], datos: unknown = null) {
    super(mensaje)
    this.estado = estado
    this.errores = errores
    this.datos = datos
  }
}

const CLAVE = 'hidral.sesion'

export interface Sesion {
  token: string
  usuario: string
  nombre: string
  rol: string
  operario_id: number | null
  operario: string | null
  permisos: string[]
}

export function sesionGuardada(): Sesion | null {
  try {
    const t = sessionStorage.getItem(CLAVE)
    return t ? (JSON.parse(t) as Sesion) : null
  } catch {
    return null
  }
}

export function guardarSesion(s: Sesion | null) {
  try {
    if (s) sessionStorage.setItem(CLAVE, JSON.stringify(s))
    else sessionStorage.removeItem(CLAVE)
  } catch {
    /* almacenamiento no disponible */
  }
}

export function puede(s: Sesion | null, permiso: string): boolean {
  if (!s) return false
  return s.permisos.includes('*') || s.permisos.includes(permiso)
}

let alCaducar: (() => void) | null = null
export function onSesionCaducada(f: () => void) {
  alCaducar = f
}

/** Texto del error para la persona: el de la API, o uno claro si la respuesta no trae ninguno. */
function mensajeError(estado: number, detalle: unknown): string {
  if (typeof detalle === 'string' && detalle) return detalle
  if (Array.isArray(detalle) && detalle.length) {
    // datos rechazados por la validación: «campo: motivo»
    const partes = detalle.slice(0, 5).map((e: { loc?: unknown[]; msg?: string }) => {
      const campo = Array.isArray(e?.loc) ? e.loc.filter((x) => x !== 'body' && x !== 'query' && x !== 'path').join('.') : ''
      return campo ? `${campo}: ${e?.msg ?? 'no válido'}` : (e?.msg ?? 'no válido')
    })
    return `Datos no válidos (${partes.join('; ')})`
  }
  if (estado === 413) return 'El fichero o los datos enviados son demasiado grandes.'
  if (estado === 429) return 'Demasiados intentos. Espera unos minutos.'
  if (estado === 502 || estado === 503 || estado === 504) return `El servidor no responde ahora mismo (error ${estado}). Inténtalo de nuevo en unos segundos.`
  return `Error ${estado}`
}

async function peticion<T>(metodo: string, ruta: string, cuerpo?: unknown, formulario?: FormData): Promise<T> {
  const s = sesionGuardada()
  const cabeceras: Record<string, string> = {}
  if (s) cabeceras.Authorization = `Bearer ${s.token}`
  if (cuerpo !== undefined) cabeceras['Content-Type'] = 'application/json'
  let estado: number
  let texto: string
  if (NAVEGADOR) {
    let bytes: Uint8Array | null = null
    if (formulario) {
      const r = new Response(formulario)
      cabeceras['Content-Type'] = r.headers.get('content-type') ?? 'multipart/form-data'
      bytes = new Uint8Array(await r.arrayBuffer())
    } else if (cuerpo !== undefined) bytes = new TextEncoder().encode(JSON.stringify(cuerpo))
    const r = await pedirMotor(metodo, `/api${ruta}`, cabeceras, bytes)
    estado = r.estado
    texto = new TextDecoder().decode(r.cuerpo)
  } else {
    let r: Response
    try {
      r = await fetch(`/api${ruta}`, {
        method: metodo,
        headers: cabeceras,
        body: formulario ?? (cuerpo !== undefined ? JSON.stringify(cuerpo) : undefined),
      })
      texto = await r.text()
    } catch (e) {
      throw new ErrorApi(0, 'No hay conexión con el servidor. Comprueba la red e inténtalo de nuevo.', [], String(e))
    }
    estado = r.status
  }
  if (estado === 401 && ruta !== '/auth/login') {
    guardarSesion(null)
    alCaducar?.()
  }
  let datos: unknown = null
  try {
    datos = texto ? JSON.parse(texto) : null
  } catch {
    datos = texto
  }
  if (estado < 200 || estado >= 300) {
    const d = (datos && typeof datos === 'object' ? datos : {}) as { detail?: unknown; errores?: string[] }
    throw new ErrorApi(estado, mensajeError(estado, d.detail), Array.isArray(d.errores) ? d.errores : [], datos)
  }
  return datos as T
}

export const api = {
  get: <T>(ruta: string) => peticion<T>('GET', ruta),
  post: <T>(ruta: string, cuerpo?: unknown) => peticion<T>('POST', ruta, cuerpo ?? {}),
  patch: <T>(ruta: string, cuerpo: unknown) => peticion<T>('PATCH', ruta, cuerpo),
  put: <T>(ruta: string, cuerpo: unknown) => peticion<T>('PUT', ruta, cuerpo),
  del: <T>(ruta: string) => peticion<T>('DELETE', ruta),
  subir: <T>(ruta: string, fichero: File, campo = 'fichero') => {
    const f = new FormData()
    f.append(campo, fichero)
    return peticion<T>('POST', ruta, undefined, f)
  },
}

export function urlImagenPagina(docId: number, pagina: number): string {
  return `/api/documentos/${docId}/paginas/${pagina}/imagen`
}

// Las imágenes necesitan el token: se descargan con fetch y se convierten a URL de objeto.
export async function imagenConToken(url: string): Promise<string> {
  const s = sesionGuardada()
  if (NAVEGADOR) {
    const r = await pedirMotor('GET', url, s ? { Authorization: `Bearer ${s.token}` } : {}, null)
    if (r.estado !== 200) throw new ErrorApi(r.estado, 'No se pudo cargar la imagen')
    return URL.createObjectURL(new Blob([r.cuerpo as BlobPart], { type: r.cabeceras['content-type'] ?? 'image/png' }))
  }
  const r = await fetch(url, { headers: s ? { Authorization: `Bearer ${s.token}` } : {} })
  if (!r.ok) throw new ErrorApi(r.status, 'No se pudo cargar la imagen')
  return URL.createObjectURL(await r.blob())
}
