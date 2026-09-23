// Integración con claude.ai cuando la edición navegador se publica como página (artifact):
// pedir cambios a Claude desde la propia aplicación, descargar ficheros y guardar copias de
// los datos en la nube. Cada capacidad puede no estar disponible (otra vista, otro visor,
// edición con servidor): entonces la función devuelve null y la interfaz oculta esa opción.

import { exportarBaseDatos, NAVEGADOR, restaurarBaseDatos } from './motor'

export interface Comentarios {
  openComposer(t: { element: Element }): Promise<{ opened: boolean }>
  anchorFor(el: Element): Promise<unknown>
  sendToClaude(t: { anchor: unknown; text: string }): Promise<{ threadId: string }>
  canSendToClaude(): Promise<string>
}
interface Descargas {
  save(r: { filename: string; data: string | Blob | ArrayBuffer | ArrayBufferView }): Promise<{ status: string }>
}
interface Ficheros {
  upload(b: Blob, o?: { type?: string }): Promise<{ id: string; url: string; sizeBytes: number }>
  delete(ref: string): Promise<unknown>
}
interface Documento {
  get(): Promise<{ exists: boolean; data(): Record<string, unknown> | undefined }>
  set(d: Record<string, unknown>): Promise<void>
}
interface BaseDatos {
  doc(ruta: string): Documento
}

type Use = (nombre: string) => Promise<unknown>

async function claudeUse(): Promise<Use | null> {
  if (!NAVEGADOR) return null
  // la plataforma inyecta window.claude; puede tardar un instante tras la carga
  for (let i = 0; i < 20; i++) {
    const use = (window as unknown as { claude?: { use?: Use } }).claude?.use
    if (use) return use
    await new Promise((r) => setTimeout(r, 250))
  }
  return null
}

const cache = new Map<string, Promise<unknown>>()
export function capacidad<T>(nombre: string): Promise<T | null> {
  if (!cache.has(nombre))
    cache.set(
      nombre,
      claudeUse().then(async (use) => {
        if (!use) return null
        try {
          return (await use(nombre)) ?? null
        } catch {
          return null
        }
      }),
    )
  return cache.get(nombre) as Promise<T | null>
}

export const comentarios = () => capacidad<Comentarios>('comments')

// ------------------------------------------------------------------ descargas
export async function descargar(nombre: string, contenido: string | Blob | Uint8Array, tipo = 'text/plain'): Promise<string> {
  const d = await capacidad<Descargas>('downloads')
  if (d) {
    try {
      const r = await d.save({ filename: nombre, data: contenido as string | Blob | ArrayBufferView })
      return r.status === 'saved' || r.status === 'delivered' ? `Descargado: ${nombre}` : `Descarga: ${r.status}`
    } catch (e) {
      const code = (e as { code?: string }).code
      if (code === 'declined') return 'Descarga cancelada.'
      throw new Error(`No se pudo descargar ${nombre} (${code ?? (e as Error).message})`, { cause: e })
    }
  }
  // edición con servidor o navegador normal: descarga clásica
  const blob = contenido instanceof Blob ? contenido : new Blob([contenido as BlobPart], { type: tipo })
  const a = document.createElement('a')
  a.href = URL.createObjectURL(blob)
  a.download = nombre
  document.body.appendChild(a)
  a.click()
  setTimeout(() => {
    URL.revokeObjectURL(a.href)
    a.remove()
  }, 1000)
  return `Descargado: ${nombre}`
}

/** CSV con separador «;» y coma decimal, como lo abre Excel en español. */
export function aCsv(filas: Record<string, unknown>[], columnas: [string, string][]): string {
  const celda = (v: unknown) => {
    if (v === null || v === undefined) return ''
    const t = typeof v === 'number' ? String(v).replace('.', ',') : String(v)
    return /[;"\n]/.test(t) ? `"${t.replace(/"/g, '""')}"` : t
  }
  const cab = columnas.map(([, t]) => celda(t)).join(';')
  return '﻿' + [cab, ...filas.map((f) => columnas.map(([k]) => celda(f[k])).join(';'))].join('\r\n')
}

// ------------------------------------------------------------------ copias de seguridad
// Formato: JSON con la base de datos SQLite comprimida (gzip) en base64. Sirve igual para
// descargarla, subirla a la nube de la página y restaurarla.

async function comprimir(bytes: Uint8Array): Promise<Uint8Array> {
  const s = new Blob([bytes as BlobPart]).stream().pipeThrough(new CompressionStream('gzip'))
  return new Uint8Array(await new Response(s).arrayBuffer())
}
async function descomprimir(bytes: Uint8Array): Promise<Uint8Array> {
  const s = new Blob([bytes as BlobPart]).stream().pipeThrough(new DecompressionStream('gzip'))
  return new Uint8Array(await new Response(s).arrayBuffer())
}
function aBase64(b: Uint8Array): string {
  let t = ''
  for (let i = 0; i < b.length; i += 0x8000) t += String.fromCharCode(...b.subarray(i, i + 0x8000))
  return btoa(t)
}
function deBase64(t: string): Uint8Array {
  const s = atob(t)
  const b = new Uint8Array(s.length)
  for (let i = 0; i < s.length; i++) b[i] = s.charCodeAt(i)
  return b
}

export interface Copia {
  formato: 'hidral-copia'
  version: 1
  fecha: string
  bytes_bd: number
  bd_gzip_base64: string
}

export async function crearCopia(): Promise<Copia> {
  const bd = await exportarBaseDatos()
  return { formato: 'hidral-copia', version: 1, fecha: new Date().toISOString(), bytes_bd: bd.length, bd_gzip_base64: aBase64(await comprimir(bd)) }
}

export async function restaurarCopia(texto: string): Promise<Copia> {
  const c = JSON.parse(texto) as Copia
  if (c.formato !== 'hidral-copia' || !c.bd_gzip_base64) throw new Error('El fichero no es una copia de HIDRAL.')
  await restaurarBaseDatos(await descomprimir(deBase64(c.bd_gzip_base64)))
  return c
}

export interface CopiaNube {
  asset_id: string
  fecha: string
  bytes: number
  anteriores?: string[]
}

const RUTA_COPIA = 'copias/actual'

export async function copiaEnNube(): Promise<CopiaNube | null> {
  const db = await capacidad<BaseDatos>('db')
  if (!db) return null
  try {
    const s = await db.doc(RUTA_COPIA).get()
    return s.exists ? (s.data() as unknown as CopiaNube) : null
  } catch {
    return null
  }
}

/** Sube una copia a la nube de la página; conserva las dos anteriores. */
export async function guardarEnNube(): Promise<CopiaNube> {
  const [db, ficheros] = await Promise.all([capacidad<BaseDatos>('db'), capacidad<Ficheros>('assets')])
  if (!db || !ficheros) throw new Error('La copia en la nube no está disponible en esta vista.')
  const copia = await crearCopia()
  const texto = JSON.stringify(copia)
  const subido = await ficheros.upload(new Blob([texto], { type: 'application/json' }), { type: 'application/json' })
  const previa = await copiaEnNube()
  const anteriores = [previa?.asset_id, ...(previa?.anteriores ?? [])].filter(Boolean) as string[]
  for (const viejo of anteriores.slice(2)) await ficheros.delete(viejo).catch(() => {})
  const doc: CopiaNube = { asset_id: subido.id, fecha: copia.fecha, bytes: subido.sizeBytes, anteriores: anteriores.slice(0, 2) }
  await db.doc(RUTA_COPIA).set(doc as unknown as Record<string, unknown>)
  return doc
}

export async function restaurarDeNube(c: CopiaNube): Promise<Copia> {
  const r = await fetch('/_blob/' + c.asset_id)
  if (!r.ok) throw new Error(`No se pudo leer la copia de la nube (HTTP ${r.status}).`)
  return restaurarCopia(await r.text())
}
