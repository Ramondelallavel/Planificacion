// Motor de HIDRAL en el navegador: el backend Python completo ejecutándose en Pyodide
// (WebAssembly) dentro de este Web Worker. La interfaz le envía peticiones HTTP como
// mensajes y este worker se las pasa a la aplicación FastAPI (hidral_plan.navegador).
//
// Los datos (/datos: base SQLite y PDF originales) se guardan en IndexedDB del navegador.

import { loadPyodide } from './pyodide/pyodide.mjs'

let py = null
let nav = null
let secreto = null
let manifiesto = null

// Python no es reentrante: todas las llamadas pasan por esta cola, de una en una.
let cola = Promise.resolve()
function enCola(tarea) {
  const p = cola.then(tarea, tarea)
  cola = p.catch(() => {})
  return p
}

const avisar = (mensaje, transferir) => postMessage(mensaje, transferir ?? [])
const url = (ruta) => new URL(ruta, import.meta.url)
const aJs = (px) => {
  if (px === undefined || px === null) return null
  const o = px.toJs({ dict_converter: Object.fromEntries })
  px.destroy()
  return o
}

async function descargar(ruta) {
  const r = await fetch(url(ruta))
  if (!r.ok) throw new Error(`No se pudo descargar ${ruta} (HTTP ${r.status})`)
  return new Uint8Array(await r.arrayBuffer())
}

// Los archivos binarios se publican como texto base64 (.txt): la página solo sirve tipos web estándar.
function deBase64(texto) {
  if (Uint8Array.fromBase64) return Uint8Array.fromBase64(texto)
  const s = atob(texto)
  const b = new Uint8Array(s.length)
  for (let i = 0; i < s.length; i++) b[i] = s.charCodeAt(i)
  return b
}
async function descargarBase64(ruta) {
  const r = await fetch(url(ruta))
  if (!r.ok) throw new Error(`No se pudo descargar ${ruta} (HTTP ${r.status})`)
  return deBase64((await r.text()).trim())
}

function unir(partes) {
  if (partes.length === 1) return partes[0]
  const total = partes.reduce((n, p) => n + p.length, 0)
  const salida = new Uint8Array(total)
  let pos = 0
  for (const p of partes) {
    salida.set(p, pos)
    pos += p.length
  }
  return salida
}

function sincronizar(cargar) {
  return new Promise((ok, mal) => py.FS.syncfs(cargar, (e) => (e ? mal(e) : ok())))
}

// Guardado en IndexedDB agrupado: tras cada cambio, como mucho uno cada medio segundo.
let temporizador = null
function programarGuardado() {
  clearTimeout(temporizador)
  temporizador = setTimeout(() => {
    sincronizar(false).then(
      () => avisar({ tipo: 'guardado' }),
      (e) => avisar({ tipo: 'aviso', mensaje: 'No se pudo guardar en el navegador: ' + (e?.message ?? e) }),
    )
  }, 500)
}

function existe(ruta) {
  try {
    py.FS.stat(ruta)
    return true
  } catch {
    return false
  }
}

async function arrancar() {
  avisar({ tipo: 'carga', fase: 'Cargando Python (WebAssembly)', pct: 3 })
  manifiesto = await (await fetch(url('./paquetes.json'))).json()
  const biblioteca = unir(await Promise.all(manifiesto.biblioteca.partes.map(descargarBase64)))
  const stdLibURL = URL.createObjectURL(new Blob([biblioteca], { type: 'application/zip' }))
  py = await loadPyodide({ indexURL: url('./pyodide/').href, stdLibURL, stdout: () => {}, stderr: (t) => console.warn('[python]', t) })
  URL.revokeObjectURL(stdLibURL)
  // descargas en paralelo, instalación en orden
  let descargados = 0
  const total = manifiesto.paquetes.reduce((n, p) => n + p.bytes, 0)
  const descargas = manifiesto.paquetes.map((p) =>
    Promise.all(p.partes.map(descargarBase64)).then((partes) => {
      descargados += p.bytes
      avisar({ tipo: 'carga', fase: `Descargando componentes (${Math.round(descargados / 1048576)} de ${Math.round(total / 1048576)} MB)`, pct: 5 + Math.round((70 * descargados) / total) })
      return unir(partes)
    }),
  )
  for (let i = 0; i < manifiesto.paquetes.length; i++) {
    const p = manifiesto.paquetes[i]
    const datos = await descargas[i]
    py.unpackArchive(datos, p.tipo, p.destino ? { extractDir: p.destino } : undefined)
  }
  py.runPython("import sys\nif '/app' not in sys.path: sys.path.insert(0, '/app')")

  avisar({ tipo: 'carga', fase: 'Abriendo tus datos guardados en este navegador', pct: 80 })
  py.FS.mkdirTree('/datos')
  py.FS.mount(py.FS.filesystems.IDBFS, {}, '/datos')
  await sincronizar(true)
  if (existe('/datos/.secreto')) secreto = py.FS.readFile('/datos/.secreto', { encoding: 'utf8' })
  else {
    const b = crypto.getRandomValues(new Uint8Array(32))
    secreto = Array.from(b, (x) => x.toString(16).padStart(2, '0')).join('')
    py.FS.writeFile('/datos/.secreto', secreto)
  }

  avisar({ tipo: 'carga', fase: 'Preparando el motor de planificación', pct: 88 })
  nav = py.pyimport('hidral_plan.navegador')
  const config = await (await fetch(url(manifiesto.config))).text()
  const r = aJs(nav.preparar(secreto, config))
  if (r.base_nueva && manifiesto.ejemplo) {
    avisar({ tipo: 'carga', fase: 'Cargando una tanda de ejemplo y generando el primer plan', pct: 93 })
    const pdf = await descargar(manifiesto.ejemplo)
    aJs(nav.cargar_ejemplo(pdf, manifiesto.ejemplo.split('/').pop()))
  }
  await sincronizar(false)
  setTimeout(procesarPendientes, 0)
  return { base_nueva: r.base_nueva }
}

let procesando = false
async function procesarPendientes() {
  if (procesando || !nav) return
  procesando = true
  try {
    for (;;) {
      const r = await enCola(() => aJs(nav.procesar_paso()))
      if (!r) break
      avisar({ tipo: 'procesando', ...r })
      programarGuardado()
      await new Promise((ok) => setTimeout(ok, 0)) // deja pasar las consultas de progreso
    }
  } catch (e) {
    avisar({ tipo: 'aviso', mensaje: 'Error procesando el documento: ' + (e?.message ?? e) })
  } finally {
    procesando = false
    avisar({ tipo: 'cambio' })
  }
}

async function peticion({ metodo, ruta, cabeceras, cuerpo }) {
  const r = await enCola(async () => aJs(await nav.peticion(metodo, ruta, py.toPy(cabeceras ?? {}), cuerpo ?? null)))
  if (metodo !== 'GET' && r.estado < 400) {
    programarGuardado()
    avisar({ tipo: 'cambio' })
    if (metodo === 'POST' && /^\/api\/documentos\/?$/.test(ruta)) setTimeout(procesarPendientes, 0)
  }
  const cuerpoSalida = r.cuerpo instanceof Uint8Array ? r.cuerpo : new Uint8Array(r.cuerpo ?? [])
  return { respuesta: { estado: r.estado, cabeceras: r.cabeceras, cuerpo: cuerpoSalida }, transferir: [cuerpoSalida.buffer] }
}

async function exportar() {
  const bytes = await enCola(() => {
    nav.cerrar_conexiones()
    return py.FS.readFile('/datos/hidral.db')
  })
  return { respuesta: { bytes }, transferir: [bytes.buffer] }
}

async function restaurar({ bytes }) {
  await enCola(() => {
    nav.cerrar_conexiones()
    py.FS.writeFile('/datos/hidral.db', bytes)
    nav.reabrir()
  })
  await sincronizar(false)
  return { respuesta: { ok: true } }
}

async function reiniciar({ conEjemplo }) {
  await enCola(async () => {
    nav.cerrar_conexiones()
    for (const f of ['/datos/hidral.db', '/datos/hidral.db-journal']) if (existe(f)) py.FS.unlink(f)
    const config = await (await fetch(url(manifiesto.config))).text()
    aJs(nav.preparar(secreto, config))
    if (conEjemplo && manifiesto.ejemplo) aJs(nav.cargar_ejemplo(await descargar(manifiesto.ejemplo), manifiesto.ejemplo.split('/').pop()))
  })
  await sincronizar(false)
  return { respuesta: { ok: true } }
}

const ACCIONES = { arrancar: async () => ({ respuesta: await arrancar() }), peticion, exportar, restaurar, reiniciar }

onmessage = async (e) => {
  const { id, accion, datos } = e.data
  try {
    const { respuesta, transferir } = await ACCIONES[accion](datos ?? {})
    avisar({ id, ok: true, respuesta }, transferir)
  } catch (err) {
    avisar({ id, ok: false, error: String(err?.message ?? err).slice(-4000) })
  }
}
