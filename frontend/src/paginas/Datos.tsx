import { useEffect, useState } from 'react'
import { MensajeError } from '../componentes/comunes'
import { fecha } from '../formato'
import { reiniciarBaseDatos } from '../motor'
import { copiaEnNube, crearCopia, descargar, guardarEnNube, restaurarCopia, restaurarDeNube, type CopiaNube } from '../plataforma'

const mb = (b: number) => `${(b / 1048576).toLocaleString('es-ES', { maximumFractionDigits: 1 })} MB`

/** Edición navegador: dónde están los datos, copias de seguridad y restauración. */
export default function Datos() {
  const [nube, setNube] = useState<CopiaNube | null | undefined>(undefined)
  const [msg, setMsg] = useState<string | null>(null)
  const [err, setErr] = useState<unknown>(null)
  const [ocupado, setOcupado] = useState<string | null>(null)
  const [confirmar, setConfirmar] = useState<null | 'reinicio' | 'nube'>(null)

  useEffect(() => {
    copiaEnNube().then(setNube)
  }, [])

  const hacer = async (etiqueta: string, f: () => Promise<string | void>, recargar = false) => {
    setErr(null)
    setMsg(null)
    setOcupado(etiqueta)
    try {
      const r = await f()
      if (r) setMsg(r)
      if (recargar) setTimeout(() => window.location.reload(), 800)
    } catch (e) {
      setErr(e)
    } finally {
      setOcupado(null)
    }
  }

  return (
    <>
      <div className="cabecera">
        <div>
          <h1>Datos y copias</h1>
          <div className="sub">Esta aplicación funciona entera en tu navegador: el motor de planificación y tus datos están en este equipo.</div>
        </div>
      </div>
      {msg && <div className="mensaje ok">{msg}</div>}
      <MensajeError error={err} />

      <div className="rejilla dos">
        <section className="panel">
          <h2>Dónde están tus datos</h2>
          <p>
            Las tandas importadas, planes, fichajes, incidencias y configuración se guardan en <strong>este navegador</strong> (almacenamiento local de la página) cada vez que cambian. Si abres
            la aplicación en otro equipo o borras los datos del navegador, empezarás desde la última copia que hayas guardado.
          </p>
          <div className="botones">
            <button
              disabled={!!ocupado}
              onClick={() =>
                hacer('descarga', async () => {
                  const c = await crearCopia()
                  const nombre = `hidral-copia-${c.fecha.slice(0, 16).replace(/[:T]/g, '-')}.json`
                  return (await descargar(nombre, JSON.stringify(c), 'application/json')) + ` (base de datos de ${mb(c.bytes_bd)})`
                })
              }
            >
              {ocupado === 'descarga' ? 'Preparando…' : 'Descargar copia'}
            </button>
            <label className="boton">
              Restaurar desde fichero
              <input
                id="restaurar-fichero"
                type="file"
                accept=".json,application/json"
                hidden
                onChange={(e) => {
                  const f = e.target.files?.[0]
                  if (f) hacer('fichero', async () => `Copia del ${fecha((await restaurarCopia(await f.text())).fecha)} restaurada. Recargando…`, true)
                }}
              />
            </label>
          </div>
        </section>

        <section className="panel">
          <h2>Copia en la nube de esta página</h2>
          {nube === undefined ? (
            <p className="tenue">Comprobando…</p>
          ) : nube === null ? (
            <p className="tenue">No hay copias en la nube, o no están disponibles en esta vista (solo las guarda quien puede editar la página).</p>
          ) : (
            <p>
              Última copia: <strong>{fecha(nube.fecha)}</strong> · {mb(nube.bytes)} comprimida. Se guarda automáticamente unos minutos después de cada cambio; Claude puede leerla si le pides
              que revise tus datos.
            </p>
          )}
          <div className="botones">
            <button
              className="primario"
              disabled={!!ocupado}
              onClick={() =>
                hacer('nube', async () => {
                  const c = await guardarEnNube()
                  setNube(c)
                  return `Copia guardada en la nube (${fecha(c.fecha)}).`
                })
              }
            >
              {ocupado === 'nube' ? 'Guardando…' : 'Guardar copia ahora'}
            </button>
            {nube && (
              <button disabled={!!ocupado} onClick={() => setConfirmar('nube')}>
                Restaurar esta copia
              </button>
            )}
          </div>
          {confirmar === 'nube' && nube && (
            <div className="mensaje aviso">
              Se sustituirán los datos de este navegador por la copia del {fecha(nube.fecha)}.
              <div className="botones" style={{ marginTop: 8 }}>
                <button className="primario" onClick={() => hacer('restaurar', async () => `Copia del ${fecha((await restaurarDeNube(nube)).fecha)} restaurada. Recargando…`, true)}>
                  Sí, restaurar
                </button>
                <button onClick={() => setConfirmar(null)}>Cancelar</button>
              </div>
            </div>
          )}
        </section>
      </div>

      <section className="panel">
        <h2>Empezar de cero</h2>
        <p className="tenue">Borra todos los datos de este navegador y vuelve a la configuración de fábrica de ejemplo. Descarga antes una copia si quieres conservarlos.</p>
        {confirmar === 'reinicio' ? (
          <div className="mensaje aviso">
            Se borrarán las tandas, planes, fichajes y cambios de configuración de este navegador.
            <div className="botones" style={{ marginTop: 8 }}>
              <button className="primario" onClick={() => hacer('reinicio', async () => (await reiniciarBaseDatos(true), 'Datos borrados. Recargando…'), true)}>
                Borrar y cargar la tanda de ejemplo
              </button>
              <button onClick={() => hacer('reinicio', async () => (await reiniciarBaseDatos(false), 'Datos borrados. Recargando…'), true)}>Borrar y empezar vacío</button>
              <button onClick={() => setConfirmar(null)}>Cancelar</button>
            </div>
          </div>
        ) : (
          <button disabled={!!ocupado} onClick={() => setConfirmar('reinicio')}>
            Empezar de cero…
          </button>
        )}
      </section>
    </>
  )
}
