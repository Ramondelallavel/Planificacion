// Cliente del motor que se ejecuta en el propio navegador (edición «navegador», build con
// VITE_NAVEGADOR=1). En la edición con servidor no se usa: la API se llama por HTTP.

export const NAVEGADOR = import.meta.env.VITE_NAVEGADOR === '1'

export interface RespuestaMotor {
  estado: number
  cabeceras: Record<string, string>
  cuerpo: Uint8Array
}

export type EventoMotor =
  | { tipo: 'carga'; fase: string; pct: number }
  | { tipo: 'procesando'; trabajo_id: number; estado: string; paginas: number; total: number; fase: string }
  | { tipo: 'cambio' }
  | { tipo: 'guardado' }
  | { tipo: 'aviso'; mensaje: string }

let worker: Worker | null = null
let siguiente = 1
const pendientes = new Map<number, { ok: (v: unknown) => void; mal: (e: Error) => void }>()
const oyentes = new Set<(e: EventoMotor) => void>()

export function onMotor(f: (e: EventoMotor) => void): () => void {
  oyentes.add(f)
  return () => oyentes.delete(f)
}

function llamar<T>(accion: string, datos?: unknown, transferir: Transferable[] = []): Promise<T> {
  if (!worker) return Promise.reject(new Error('El motor no está iniciado'))
  const id = siguiente++
  return new Promise<T>((ok, mal) => {
    pendientes.set(id, { ok: ok as (v: unknown) => void, mal })
    worker!.postMessage({ id, accion, datos }, transferir)
  })
}

export function iniciarMotor(): Promise<{ base_nueva: boolean }> {
  if (!worker) {
    worker = new Worker(new URL('motor/motor.js', document.baseURI), { type: 'module' })
    worker.onmessage = (e: MessageEvent) => {
      const m = e.data
      if (m.id !== undefined) {
        const p = pendientes.get(m.id)
        pendientes.delete(m.id)
        if (p && m.ok) p.ok(m.respuesta)
        else if (p) p.mal(new Error(m.error))
      } else oyentes.forEach((f) => f(m as EventoMotor))
    }
    worker.onerror = (e) => oyentes.forEach((f) => f({ tipo: 'aviso', mensaje: 'El motor se ha detenido: ' + (e.message || 'error desconocido') }))
  }
  return llamar('arrancar')
}

export function pedirMotor(metodo: string, ruta: string, cabeceras: Record<string, string>, cuerpo: Uint8Array | null): Promise<RespuestaMotor> {
  return llamar<RespuestaMotor>('peticion', { metodo, ruta, cabeceras, cuerpo }, cuerpo ? [cuerpo.buffer as ArrayBuffer] : [])
}

/** Copia completa de la base de datos (fichero SQLite). */
export function exportarBaseDatos(): Promise<Uint8Array> {
  return llamar<{ bytes: Uint8Array }>('exportar').then((r) => r.bytes)
}

export function restaurarBaseDatos(bytes: Uint8Array): Promise<void> {
  return llamar('restaurar', { bytes }, [bytes.buffer as ArrayBuffer])
}

export function reiniciarBaseDatos(conEjemplo: boolean): Promise<void> {
  return llamar('reiniciar', { conEjemplo })
}
