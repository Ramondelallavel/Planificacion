// Cliente de la API REST. El token se guarda en sessionStorage (se pierde al cerrar la pestaña).

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

async function peticion<T>(metodo: string, ruta: string, cuerpo?: unknown, formulario?: FormData): Promise<T> {
  const s = sesionGuardada()
  const cabeceras: Record<string, string> = {}
  if (s) cabeceras.Authorization = `Bearer ${s.token}`
  if (cuerpo !== undefined) cabeceras['Content-Type'] = 'application/json'
  const r = await fetch(`/api${ruta}`, {
    method: metodo,
    headers: cabeceras,
    body: formulario ?? (cuerpo !== undefined ? JSON.stringify(cuerpo) : undefined),
  })
  if (r.status === 401 && ruta !== '/auth/login') {
    guardarSesion(null)
    alCaducar?.()
  }
  const texto = await r.text()
  let datos: unknown = null
  try {
    datos = texto ? JSON.parse(texto) : null
  } catch {
    datos = texto
  }
  if (!r.ok) {
    const d = (datos ?? {}) as { detail?: unknown; errores?: string[] }
    const detalle = typeof d.detail === 'string' ? d.detail : `Error ${r.status}`
    throw new ErrorApi(r.status, detalle, d.errores ?? [], datos)
  }
  return datos as T
}

export const api = {
  get: <T>(ruta: string) => peticion<T>('GET', ruta),
  post: <T>(ruta: string, cuerpo?: unknown) => peticion<T>('POST', ruta, cuerpo ?? {}),
  patch: <T>(ruta: string, cuerpo: unknown) => peticion<T>('PATCH', ruta, cuerpo),
  put: <T>(ruta: string, cuerpo: unknown) => peticion<T>('PUT', ruta, cuerpo),
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
  const r = await fetch(url, { headers: s ? { Authorization: `Bearer ${s.token}` } : {} })
  if (!r.ok) throw new ErrorApi(r.status, 'No se pudo cargar la imagen')
  return URL.createObjectURL(await r.blob())
}
