import { useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { api, puede } from '../api'
import { useSesion } from '../App'
import { Cargando, ExplicacionDecision, MensajeError, Modal, Riesgo, useDatos } from '../componentes/comunes'
import { fecha, horas, isoLocal, semana } from '../formato'
import type { Explicacion, NoPlanificada, OFResumen } from '../tipos'
import { VisorPagina } from './Documento'
import { EditarOperacion, NuevaOperacion, type OpEditable } from '../componentes/EditorOperaciones'

interface Dep {
  id: number
  numero: string
  seccion: string | null
  estado: string | null
  grupo_hf: string | null
  tipo: string
  fuente: string
  evidencias: { pagina?: number; articulo?: string; tipo?: string; descripcion?: string }[] | null
}

interface OFDet extends OFResumen {
  seccion_completa: string | null
  grupo_conj: string | null
  consumos: { articulo: string | null; descripcion: string | null; total: number | null; total_texto: string; pagina: number; tipo: string }[] | null
  documento_id: number | null
  fuente: string
  parametros_extra: Record<string, unknown> | null
  aparatos: { id: number; referencia: string; lineas: number }[]
  operaciones: {
    id: number
    secuencia: number
    tipo: string
    descripcion: string | null
    seccion: string | null
    recurso_preferido: string | null
    duracion_estimada_min: number | null
    duracion_real_min: number | null
    origen_duracion: string | null
    estado: string
    requiere_programa: boolean
    cantidad: number | null
    cantidad_hecha: number
    fuente: string
    familia_setup: string | null
    plan: { inicio: string; fin: string; recurso: string | null; explicacion: Explicacion | null; bloqueada: boolean; provisional: boolean } | null
    no_planificada: NoPlanificada | null
  }[]
  lineas: {
    id: number
    tipo: string
    articulo: string | null
    descripcion: string | null
    posicion: string | null
    id_pieza: string | null
    parametros: string | null
    cantidad: number | null
    cantidad_texto: string | null
    detalle_corte: string | null
    material: string | null
    espesor_mm: number | null
    largo_mm: number | null
    ancho_mm: number | null
    numero_control: string | null
    seccion_ref: string | null
    orden_ref: string | null
    orden_plegado: string | null
    operaciones_marcadas: string[] | null
    pagina: number | null
    texto_origen: string | null
  }[]
  predecesoras: Dep[]
  sucesoras: Dep[]
  incidencias_datos: { id: number; tipo: string; severidad: string; mensaje: string; pagina: number | null; estado: string }[]
  programas: { codigo: string; fuente: string; estado: string; recurso: string | null; registrado: string; por: string | null }[]
  riesgo_detalle: { nivel: string; motivos: string[]; fin_previsto: string | null; holgura_h: number | null; horas_restantes: number } | null
}

interface Origen {
  campo: string | null
  fuente: string
  documento: string | null
  clave_documento: string | null
  documento_id: number | null
  pagina: number | null
  bloque: number | null
  texto_origen: string | null
  detalle: string | null
}

const TIPO_LINEA: Record<string, string> = {
  SALIDA: 'Salida → destino',
  SALIDA_INTERNA: 'Salida interna',
  ENTRADA: 'Componente ← OF',
  ENTRADA_INTERNA: 'Componente interno',
  ENTRADA_COMPRA: 'Compra / almacén',
  CONSUMO_MATERIAL: 'Consumo de material',
  PIEZA_CHAPA: 'Pieza de chapa',
}

export default function OF() {
  const id = Number(useParams().id)
  const nav = useNavigate()
  const { sesion } = useSesion()
  const { datos: o, error, recargar } = useDatos(() => api.get<OFDet>(`/ofs/${id}`), [id])
  const origen = useDatos(() => api.get<Origen[]>(`/trazabilidad/OF/${id}`), [id])
  const [pestana, setPestana] = useState('operaciones')
  const [pagina, setPagina] = useState<number | null>(null)
  const [explic, setExplic] = useState<Explicacion | null>(null)
  const [accion, setAccion] = useState<string | null>(null)
  const [editarOp, setEditarOp] = useState<OpEditable | 'nueva' | null>(null)
  const [errOp, setErrOp] = useState<unknown>(null)
  if (error) return <MensajeError error={error} />
  if (!o) return <Cargando />
  const modificar = puede(sesion, 'modificar_plan')
  return (
    <>
      <div className="cabecera">
        <div>
          <h1>
            OF {o.numero} <Riesgo nivel={o.riesgo} texto /> {o.urgente && <span className="riesgo ROJO">URGENTE</span>}
          </h1>
          <div className="sub">
            {o.descripcion} · sección {o.seccion_completa ?? o.seccion ?? '—'} · grupo HF {o.grupo_hf ?? '—'} {o.modo && `· ${o.modo}`} · {semana(o.semana)} · estado <strong>{o.estado}</strong>
            {o.programa && ` · programa ${o.programa}`} · fuente {o.fuente}
            {!o.tiene_hoja && <strong> · OF referenciada sin hoja en el documento</strong>}
          </div>
          <div className="sub">
            Aparato(s): {o.aparatos.length ? o.aparatos.map((a) => <Link key={a.id} to={`/aparatos/${a.id}`} style={{ marginRight: 8 }}>{a.referencia}</Link>) : <span className="nd">ninguno identificado</span>}
            · Páginas: {(o.paginas ?? []).map((p) => (o.documento_id ? <a key={p} style={{ cursor: 'pointer', marginRight: 6 }} onClick={() => setPagina(p)}>{p}</a> : p))}
          </div>
        </div>
        {modificar && (
          <div className="botones">
            <button onClick={() => nav(`/simulacion?of=${o.id}`)}>Introducir como urgente…</button>
            <button onClick={() => setAccion('bloquear')}>{o.bloqueada ? 'Desbloquear' : 'Bloquear'}</button>
            <button onClick={() => setAccion('material')}>Material</button>
            {o.estado_programacion === 'PENDIENTE_PROGRAMACION' && (
              <button className="primario" onClick={() => setAccion('programa')}>
                Registrar programa
              </button>
            )}
            {!o.tiene_hoja && <button onClick={() => setAccion('disponible')}>Fecha prevista (externa)</button>}
            <button className="peligro" onClick={() => setAccion('eliminar')}>
              Eliminar OF
            </button>
          </div>
        )}
      </div>
      {o.riesgo_detalle && (
        <div className={`mensaje ${o.riesgo_detalle.nivel === 'ROJO' ? 'error' : o.riesgo_detalle.nivel === 'VERDE' ? 'ok' : 'aviso'}`}>
          Fin previsto {fecha(o.riesgo_detalle.fin_previsto)} · holgura {o.riesgo_detalle.holgura_h === null ? '—' : horas(o.riesgo_detalle.holgura_h)} · {horas(o.riesgo_detalle.horas_restantes)} pendientes
          {o.riesgo_detalle.motivos.length > 0 && (
            <ul>
              {o.riesgo_detalle.motivos.map((m, i) => (
                <li key={i}>{m}</li>
              ))}
            </ul>
          )}
        </div>
      )}
      <div className="pestanas">
        {[
          ['operaciones', `Operaciones (${o.operaciones.length})`],
          ['lineas', `Piezas / líneas (${o.lineas.length})`],
          ['dependencias', `Dependencias (${o.predecesoras.length}↑ ${o.sucesoras.length}↓)`],
          ['origen', 'Trazabilidad'],
          ['incidencias', `Incidencias de datos (${o.incidencias_datos.length})`],
        ].map(([k, t]) => (
          <button key={k} className={pestana === k ? 'activa' : ''} onClick={() => setPestana(k)}>
            {t}
          </button>
        ))}
      </div>
      {pestana === 'operaciones' && (
        <section className="panel">
          <table>
            <thead>
              <tr>
                <th>Seq.</th>
                <th>Operación</th>
                <th>Estado</th>
                <th className="num">Estimado</th>
                <th className="num">Real</th>
                <th>Origen de la duración</th>
                <th>Plan</th>
                {modificar && <th />}
              </tr>
            </thead>
            <tbody>
              {o.operaciones.map((op) => (
                <tr key={op.id}>
                  <td>{op.secuencia}</td>
                  <td>
                    <strong>{op.tipo}</strong> {op.recurso_preferido && <span className="etiqueta">máquina {op.recurso_preferido}</span>}
                    <div className="pequeno tenue">{op.descripcion}</div>
                    {op.familia_setup && <div className="pequeno tenue">familia setup: {op.familia_setup}</div>}
                  </td>
                  <td className="pequeno">{op.estado}</td>
                  <td className="num">{op.duracion_estimada_min === null ? <span className="nd">DATO NO DISPONIBLE</span> : `${op.duracion_estimada_min} min`}</td>
                  <td className="num">{op.duracion_real_min === null ? '—' : `${op.duracion_real_min} min`}</td>
                  <td className="pequeno">
                    {op.origen_duracion} {op.origen_duracion?.includes('EJEMPLO') && <span className="etiqueta ejemplo">EJEMPLO</span>}
                  </td>
                  <td className="pequeno">
                    {op.plan ? (
                      <>
                        {fecha(op.plan.inicio)} → {fecha(op.plan.fin)} en <strong>{op.plan.recurso}</strong>
                        {op.plan.provisional && <span className="etiqueta"> provisional</span>}
                        {op.plan.bloqueada && <span className="etiqueta"> bloqueada</span>}
                        <div>
                          <a style={{ cursor: 'pointer' }} onClick={() => setExplic(op.plan!.explicacion)}>
                            ¿Por qué?
                          </a>
                        </div>
                      </>
                    ) : op.no_planificada ? (
                      <span>
                        <Riesgo nivel="ROJO" /> {op.no_planificada.motivo}: {op.no_planificada.detalle}
                      </span>
                    ) : (
                      '—'
                    )}
                  </td>
                  {modificar && (
                    <td>
                      {op.estado !== 'TERMINADA' && (
                        <div className="botones">
                          <button onClick={() => setEditarOp(op)}>Editar</button>
                          {!['EN_CURSO', 'PAUSADA'].includes(op.estado) && o.operaciones.length > 1 && (
                            <button
                              onClick={async () => {
                                setErrOp(null)
                                try {
                                  await api.del(`/operaciones/${op.id}`)
                                  recargar()
                                } catch (e) {
                                  setErrOp(e)
                                }
                              }}
                            >
                              Quitar
                            </button>
                          )}
                        </div>
                      )}
                    </td>
                  )}
                </tr>
              ))}
            </tbody>
          </table>
          <MensajeError error={errOp} />
          {modificar && !['TERMINADA', 'VALIDADA'].includes(o.estado) && (
            <div className="botones" style={{ marginTop: 8 }}>
              <button onClick={() => setEditarOp('nueva')}>+ Añadir operación</button>
              <span className="pequeno tenue">Los cambios se aplican al plan al replanificar.</span>
            </div>
          )}
          {editarOp === 'nueva' && (
            <NuevaOperacion
              ofId={o.id}
              ops={o.operaciones}
              seccionOF={o.seccion}
              onCerrar={() => setEditarOp(null)}
              onHecho={() => {
                setEditarOp(null)
                recargar()
              }}
            />
          )}
          {editarOp && editarOp !== 'nueva' && (
            <EditarOperacion
              op={editarOp}
              onCerrar={() => setEditarOp(null)}
              onHecho={() => {
                setEditarOp(null)
                recargar()
              }}
            />
          )}
          {o.consumos && o.consumos.length > 0 && (
            <>
              <h3 style={{ marginTop: 12 }}>Consumos de material</h3>
              <ul className="lista-plana">
                {o.consumos.map((c, i) => (
                  <li key={i} className="pequeno">
                    <span className="mono">{c.articulo}</span> {c.descripcion} · total {c.total_texto} ({c.tipo}, p.{c.pagina})
                  </li>
                ))}
              </ul>
            </>
          )}
          {o.programas.length > 0 && (
            <p className="pequeno">
              Programas: {o.programas.map((p) => `${p.codigo} (${p.fuente}${p.recurso ? ', ' + p.recurso : ''}, ${fecha(p.registrado)})`).join(' · ')}
            </p>
          )}
        </section>
      )}
      {pestana === 'lineas' && (
        <section className="panel">
          <table>
            <thead>
              <tr>
                <th>Tipo</th>
                <th>Artículo</th>
                <th>Descripción</th>
                <th className="num">Cant.</th>
                <th>Material / dims</th>
                <th>Nº control</th>
                <th>Origen / destino</th>
                <th>Parámetros</th>
                <th>Pág.</th>
              </tr>
            </thead>
            <tbody>
              {o.lineas.map((l) => (
                <tr key={l.id} title={l.texto_origen ?? ''}>
                  <td className="pequeno">{TIPO_LINEA[l.tipo] ?? l.tipo}</td>
                  <td className="mono">
                    {l.posicion && <span className="tenue">{l.posicion}-</span>}
                    {l.articulo}
                    {l.id_pieza && <div className="tenue">{l.id_pieza}</div>}
                  </td>
                  <td>{l.descripcion}</td>
                  <td className="num">
                    {l.cantidad ?? <span className="nd">N/D</span>}
                    {l.detalle_corte && <div className="tenue mono">{l.detalle_corte}</div>}
                  </td>
                  <td className="pequeno">{l.material ? `${l.material} ${l.espesor_mm} × ${l.largo_mm} × ${l.ancho_mm}` : ''}</td>
                  <td>{l.numero_control}</td>
                  <td className="pequeno">
                    {l.orden_plegado && <div>Pleg. → OF {l.orden_plegado}</div>}
                    {l.orden_ref && (
                      <span>
                        {l.tipo.startsWith('ENTRADA') ? '← ' : '→ '}
                        {l.seccion_ref} {l.orden_ref}
                      </span>
                    )}
                    {l.operaciones_marcadas && l.operaciones_marcadas.length > 0 && <div className="tenue">{l.operaciones_marcadas.join(', ')}</div>}
                  </td>
                  <td className="pequeno mono">{l.parametros}</td>
                  <td>{l.pagina && o.documento_id ? <a style={{ cursor: 'pointer' }} onClick={() => setPagina(l.pagina)}>{l.pagina}</a> : l.pagina}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      )}
      {pestana === 'dependencias' && (
        <div className="rejilla dos">
          <TablaDeps titulo="Depende de (predecesoras)" deps={o.predecesoras} />
          <TablaDeps titulo="La necesitan (sucesoras)" deps={o.sucesoras} />
        </div>
      )}
      {pestana === 'origen' && (
        <section className="panel">
          <p className="pequeno tenue">De dónde procede cada dato: fuente, documento, página, bloque y texto original.</p>
          {!origen.datos ? (
            <Cargando />
          ) : (
            <table>
              <thead>
                <tr>
                  <th>Campo</th>
                  <th>Fuente</th>
                  <th>Documento</th>
                  <th>Página</th>
                  <th>Bloque</th>
                  <th>Texto de origen</th>
                </tr>
              </thead>
              <tbody>
                {origen.datos.map((x, i) => (
                  <tr key={i}>
                    <td>{x.campo ?? 'registro'}</td>
                    <td>
                      <span className="etiqueta">{x.fuente}</span>
                    </td>
                    <td className="pequeno">
                      {x.documento_id ? <Link to={`/documentos/${x.documento_id}`}>{x.clave_documento ?? x.documento}</Link> : x.detalle}
                    </td>
                    <td>{x.pagina && x.documento_id ? <a style={{ cursor: 'pointer' }} onClick={() => setPagina(x.pagina)}>{x.pagina}</a> : x.pagina ?? '—'}</td>
                    <td>{x.bloque ?? '—'}</td>
                    <td className="mono pequeno">{x.texto_origen}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </section>
      )}
      {pestana === 'incidencias' && (
        <section className="panel">
          {o.incidencias_datos.length === 0 ? (
            <p className="tenue">Sin incidencias de datos para esta OF.</p>
          ) : (
            <ul className="lista-plana">
              {o.incidencias_datos.map((i) => (
                <li key={i.id}>
                  <span className="etiqueta">{i.severidad}</span> <span className="mono">{i.tipo}</span> {i.mensaje} {i.pagina && `(p.${i.pagina})`} · {i.estado}
                </li>
              ))}
            </ul>
          )}
        </section>
      )}
      {pagina && o.documento_id && <VisorPagina docId={o.documento_id} pagina={pagina} onCerrar={() => setPagina(null)} />}
      {explic && (
        <Modal titulo={`¿Por qué? · OF ${o.numero}`} onCerrar={() => setExplic(null)}>
          <ExplicacionDecision e={explic} />
        </Modal>
      )}
      {accion && (
        <AccionOF
          of={o}
          accion={accion}
          onCerrar={() => setAccion(null)}
          onHecho={() => {
            setAccion(null)
            recargar()
          }}
        />
      )}
    </>
  )
}

function TablaDeps({ titulo, deps }: { titulo: string; deps: Dep[] }) {
  return (
    <section className="panel">
      <h2>{titulo}</h2>
      {deps.length === 0 ? (
        <p className="tenue">Ninguna.</p>
      ) : (
        <table>
          <thead>
            <tr>
              <th>OF</th>
              <th>Sección / grupo</th>
              <th>Estado</th>
              <th>Relación</th>
              <th>Evidencia</th>
            </tr>
          </thead>
          <tbody>
            {deps.map((d) => (
              <tr key={d.id}>
                <td>
                  <Link to={`/ofs/${d.id}`}>{d.numero}</Link>
                </td>
                <td className="pequeno">
                  {d.seccion} · {d.grupo_hf}
                </td>
                <td className="pequeno">{d.estado}</td>
                <td className="pequeno">
                  {d.tipo} <span className="tenue">({d.fuente})</span>
                </td>
                <td className="pequeno">
                  {(d.evidencias ?? [])
                    .slice(0, 4)
                    .map((e) => (e.descripcion ? `regla: ${e.descripcion}` : `p.${e.pagina} ${e.articulo ?? ''} (${e.tipo})`))
                    .join(' · ')}
                  {(d.evidencias ?? []).length > 1 && new Set((d.evidencias ?? []).map((e) => e.tipo)).size > 1 && <span className="etiqueta" style={{ marginLeft: 4 }}>corroborada</span>}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </section>
  )
}

function AccionOF({ of, accion, onCerrar, onHecho }: { of: OFDet; accion: string; onCerrar: () => void; onHecho: () => void }) {
  const [motivo, setMotivo] = useState('')
  const [codigo, setCodigo] = useState('')
  const [fechaTxt, setFechaTxt] = useState(isoLocal(new Date()))
  const [disponible, setDisponible] = useState('si')
  const [err, setErr] = useState<unknown>(null)
  const navegar = useNavigate()
  const titulos: Record<string, string> = {
    eliminar: `Eliminar la OF ${of.numero}`,
    bloquear: of.bloqueada ? 'Desbloquear OF' : 'Bloquear OF',
    material: 'Disponibilidad de material',
    programa: 'Registrar programa de máquina',
    disponible: 'Fecha prevista de disponibilidad (OF externa / sin hoja)',
  }
  const enviar = async () => {
    try {
      if (accion === 'eliminar') {
        await api.del(`/ofs/${of.id}?motivo=${encodeURIComponent(motivo)}`)
        navegar('/ofs')
        return
      }
      if (accion === 'programa') await api.post(`/ofs/${of.id}/programa`, { codigo })
      else if (accion === 'bloquear') await api.patch(`/ofs/${of.id}`, { bloqueada: !of.bloqueada, motivo })
      else if (accion === 'material')
        await api.patch(`/ofs/${of.id}`, {
          material_disponible: disponible === 'si' ? true : disponible === 'no' ? false : null,
          material_disponible_desde: disponible === 'fecha' ? fechaTxt : null,
          motivo,
        })
      else if (accion === 'disponible') await api.patch(`/ofs/${of.id}`, { disponible_prevista: fechaTxt, motivo })
      onHecho()
    } catch (e) {
      setErr(e)
    }
  }
  return (
    <Modal titulo={titulos[accion]} onCerrar={onCerrar}>
      {accion === 'eliminar' && (
        <p>
          Se borran la OF, sus operaciones, líneas y dependencias, y sale del plan. Si ya tiene trabajo fichado no se puede eliminar. <strong>No se puede deshacer.</strong>
        </p>
      )}
      {accion === 'programa' && (
        <>
          <p className="tenue">Al registrar el programa la OF pasa a «Lista para fabricar» y el plan deja de ser provisional.</p>
          <label className="campo">
            Código de programa / nesting
            <input value={codigo} onChange={(e) => setCodigo(e.target.value)} />
          </label>
        </>
      )}
      {accion === 'material' && (
        <label className="campo">
          Material
          <select value={disponible} onChange={(e) => setDisponible(e.target.value)}>
            <option value="si">Disponible</option>
            <option value="no">No disponible (sin fecha)</option>
            <option value="fecha">Disponible a partir de…</option>
            <option value="nd">DATO NO DISPONIBLE</option>
          </select>
        </label>
      )}
      {(accion === 'disponible' || (accion === 'material' && disponible === 'fecha')) && (
        <label className="campo" style={{ marginTop: 8 }}>
          Fecha
          <input type="datetime-local" value={fechaTxt} onChange={(e) => setFechaTxt(e.target.value)} />
        </label>
      )}
      {accion !== 'programa' && (
        <label className="campo" style={{ marginTop: 8 }}>
          Motivo (queda registrado)
          <textarea value={motivo} onChange={(e) => setMotivo(e.target.value)} />
        </label>
      )}
      <MensajeError error={err} />
      <div className="botones" style={{ marginTop: 10 }}>
        <button className={accion === 'eliminar' ? 'peligro' : 'primario'} onClick={enviar} disabled={accion === 'programa' ? !codigo : !motivo}>
          {accion === 'eliminar' ? 'Eliminar definitivamente' : 'Guardar'}
        </button>
        <span className="pequeno tenue">Regenere o replanifique el plan para aplicar el cambio.</span>
      </div>
    </Modal>
  )
}
