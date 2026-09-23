import { useState } from 'react'
import { api } from '../api'
import { Cargando, MensajeError, useDatos } from '../componentes/comunes'
import { fecha } from '../formato'

interface Registro {
  id: number
  fecha: string
  usuario: string
  accion: string
  entidad_tipo: string | null
  entidad_id: string | null
  antes: unknown
  despues: unknown
  motivo: string | null
  automatica: boolean
}

function Valor({ v }: { v: unknown }) {
  if (v === null || v === undefined) return <span className="nd">—</span>
  if (typeof v !== 'object') return <span>{String(v)}</span>
  const texto = JSON.stringify(v, null, 1)
  if (texto.length < 90) return <span className="mono pequeno">{texto.replace(/\n\s*/g, ' ')}</span>
  return (
    <details>
      <summary className="pequeno">{Array.isArray(v) ? `${v.length} elementos` : `${Object.keys(v as object).length} campos`}</summary>
      <pre className="mono pequeno" style={{ whiteSpace: 'pre-wrap', maxWidth: 420, margin: 0 }}>
        {texto}
      </pre>
    </details>
  )
}

export default function Auditoria() {
  const [filtro, setFiltro] = useState({ accion: '', entidad_tipo: '', entidad_id: '', usuario: '' })
  const [aplicado, setAplicado] = useState(filtro)
  const [soloManuales, setSoloManuales] = useState(false)
  const qs = new URLSearchParams(Object.entries({ ...aplicado, limite: '500' }).filter(([, v]) => v)).toString()
  const { datos, error, recargar } = useDatos(() => api.get<Registro[]>(`/auditoria?${qs}`), [qs])
  const filas = (datos ?? []).filter((r) => !soloManuales || !r.automatica)
  const campo = (k: keyof typeof filtro, etiqueta: string, ejemplo: string) => (
    <label className="campo">
      {etiqueta}
      <input value={filtro[k]} placeholder={ejemplo} onChange={(e) => setFiltro({ ...filtro, [k]: e.target.value.trim() })} onKeyDown={(e) => e.key === 'Enter' && setAplicado(filtro)} />
    </label>
  )
  return (
    <>
      <div className="cabecera">
        <div>
          <h1>Auditoría</h1>
          <div className="sub">Registro de quién cambió qué, cuándo, con qué valor anterior y posterior y por qué. Incluye los cambios automáticos del sistema y los intentos rechazados.</div>
        </div>
        <button onClick={recargar}>Actualizar</button>
      </div>
      <section className="panel">
        <div className="formulario">
          {campo('accion', 'Acción', 'CAMBIO_MANUAL_PLAN')}
          {campo('entidad_tipo', 'Tipo de entidad', 'OF, OPERACION, PLAN…')}
          {campo('entidad_id', 'Id / referencia', '917251')}
          {campo('usuario', 'Usuario', 'planificador')}
        </div>
        <div className="botones" style={{ marginTop: 8 }}>
          <button className="primario" onClick={() => setAplicado(filtro)}>
            Filtrar
          </button>
          <button
            onClick={() => {
              const vacio = { accion: '', entidad_tipo: '', entidad_id: '', usuario: '' }
              setFiltro(vacio)
              setAplicado(vacio)
            }}
          >
            Limpiar
          </button>
          <label>
            <input type="checkbox" checked={soloManuales} onChange={(e) => setSoloManuales(e.target.checked)} /> Solo cambios manuales
          </label>
        </div>
      </section>
      <MensajeError error={error} />
      {!datos ? (
        <Cargando />
      ) : (
        <section className="panel">
          <p className="pequeno tenue">{filas.length} registros (máx. 500, los más recientes primero)</p>
          <table>
            <thead>
              <tr>
                <th>Fecha</th>
                <th>Usuario</th>
                <th>Acción</th>
                <th>Entidad</th>
                <th>Antes</th>
                <th>Después</th>
                <th>Motivo</th>
              </tr>
            </thead>
            <tbody>
              {filas.map((r) => (
                <tr key={r.id}>
                  <td className="pequeno" style={{ whiteSpace: 'nowrap' }}>
                    {fecha(r.fecha)}
                  </td>
                  <td>
                    {r.usuario}
                    {r.automatica && <div className="etiqueta">automático</div>}
                  </td>
                  <td className="mono pequeno">{r.accion}</td>
                  <td className="pequeno">
                    {r.entidad_tipo} {r.entidad_id && <span className="mono">{r.entidad_id}</span>}
                  </td>
                  <td>
                    <Valor v={r.antes} />
                  </td>
                  <td>
                    <Valor v={r.despues} />
                  </td>
                  <td className="pequeno">{r.motivo ?? <span className="nd">—</span>}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      )}
    </>
  )
}
