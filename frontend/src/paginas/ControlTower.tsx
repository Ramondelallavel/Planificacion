import { useState } from 'react'
import { Link } from 'react-router-dom'
import { api, puede } from '../api'
import { useSesion } from '../App'
import { Cargando, Kpi, MensajeError, Modal, Riesgo, useDatos } from '../componentes/comunes'
import { fecha, hora, horas, minutos, pct, semana } from '../formato'
import type { Cambio, Comprobacion, Cuello, Kpis, Nivel, RiesgoAparato, RiesgoTanda } from '../tipos'

interface Alerta {
  tanda_id: number
  tanda: string
  semana: string | null
  nivel: Nivel
  titulo: string
  detalles: { nivel: Nivel; texto: string; acciones: string[] }[]
  impacto: string[]
  fin_previsto: string | null
}

interface CT {
  ahora: string
  plan: { id: number; nombre: string; creado: string; kpis: Kpis; definitivo: boolean } | null
  resumen: Record<string, number>
  personal: { en_turno: number; ausentes: number; ocupados: number; disponibles: number; turnos_activos: string[] }
  alertas: Alerta[]
  tandas: RiesgoTanda[]
  aparatos: RiesgoAparato[]
  cuellos: Cuello[]
  maquinas_paradas: { codigo: string; nombre: string; estado: string }[]
  ahora_hacer: { operacion_id: number; of: string; of_id: number; tipo: string; recurso: string | null; operario: string | null; inicio: string; fin: string; estado: string; provisional: boolean; riesgo: Nivel; prioridad: number | null; motivo: string[] }[]
  acciones_recomendadas: { nivel: Nivel; texto: string }[]
  cambios_recientes: Cambio[]
  retrasadas: { of: string; of_id: number; motivo: string }[]
}

export default function ControlTower() {
  const { sesion } = useSesion()
  const { datos, error, recargar } = useDatos(() => api.get<CT>('/dashboard/control-tower'), [], 60000)
  const [generar, setGenerar] = useState(false)
  if (error) return <MensajeError error={error} />
  if (!datos) return <Cargando />
  const r = datos.resumen
  return (
    <>
      <div className="cabecera">
        <div>
          <h1>Control Tower</h1>
          <div className="sub">
            {fecha(datos.ahora)} · turnos activos: {datos.personal.turnos_activos.join(', ') || 'ninguno'} ·{' '}
            {datos.plan ? (
              <>
                plan «{datos.plan.nombre}» generado {fecha(datos.plan.creado)} {datos.plan.definitivo ? '(definitivo)' : '(provisional)'}
              </>
            ) : (
              <strong>sin plan activo</strong>
            )}
          </div>
        </div>
        <div className="botones">
          <button onClick={recargar}>Actualizar</button>
          {puede(sesion, 'planificar') && (
            <button className="primario" onClick={() => setGenerar(true)}>
              GENERAR PLAN
            </button>
          )}
        </div>
      </div>

      <div className="kpis">
        <Kpi valor={r.tandas_en_curso} etiqueta="Tandas en curso" />
        <Kpi valor={r.tandas_en_riesgo} etiqueta="Tandas en riesgo" nivel={r.tandas_en_riesgo ? 'ROJO' : 'VERDE'} />
        <Kpi valor={r.aparatos_en_riesgo} etiqueta="Aparatos en riesgo" nivel={r.aparatos_en_riesgo ? 'NARANJA' : 'VERDE'} />
        <Kpi valor={r.ofs_retrasadas} etiqueta="OF retrasadas" nivel={r.ofs_retrasadas ? 'NARANJA' : 'VERDE'} />
        <Kpi valor={r.maquinas_paradas} etiqueta="Máquinas paradas" nivel={r.maquinas_paradas ? 'ROJO' : 'VERDE'} />
        <Kpi valor={r.incidencias_abiertas} etiqueta="Incidencias abiertas" nivel={r.incidencias_abiertas ? 'AMARILLO' : 'VERDE'} />
        <Kpi valor={`${r.trabajadores_disponibles}/${datos.personal.en_turno}`} etiqueta="Trabajadores disponibles / en turno" />
        <Kpi valor={r.cuellos_botella} etiqueta="Cuellos de botella" nivel={r.cuellos_botella ? 'NARANJA' : 'VERDE'} />
        <Kpi valor={r.no_planificadas} etiqueta="Operaciones no planificables" nivel={r.no_planificadas ? 'ROJO' : 'VERDE'} />
      </div>

      <div className="rejilla dos">
        <section className="panel">
          <h2>¿Qué está en riesgo y por qué?</h2>
          {datos.alertas.length === 0 && <p className="tenue">No hay tandas activas.</p>}
          {datos.alertas.map((a) => (
            <details key={a.tanda_id} className={`alerta ${a.nivel}`} open={a.nivel === 'ROJO'}>
              <summary>
                <Riesgo nivel={a.nivel} texto />
                <strong>{a.titulo}</strong>
                <span className="tenue">
                  {semana(a.semana)} · fin previsto {fecha(a.fin_previsto)}
                </span>
                <Link to={`/tandas/${a.tanda_id}`} style={{ marginLeft: 'auto' }}>
                  Ver tanda →
                </Link>
              </summary>
              <div className="cuerpo">
                <ul className="lista-plana">
                  {a.detalles.map((d, i) => (
                    <li key={i}>
                      <Riesgo nivel={d.nivel} /> {d.texto}
                      {d.acciones.length > 0 && <div className="pequeno tenue">→ {d.acciones.join(' · ')}</div>}
                    </li>
                  ))}
                </ul>
                {a.impacto.length > 0 && (
                  <div className="mensaje aviso pequeno">
                    <strong>¿Qué pasa si no actúo?</strong>
                    <ul>
                      {a.impacto.map((m, i) => (
                        <li key={i}>{m}</li>
                      ))}
                    </ul>
                  </div>
                )}
              </div>
            </details>
          ))}
        </section>

        <section className="panel">
          <h2>¿Qué tengo que hacer ahora?</h2>
          <p className="pequeno tenue">Trabajos en curso o que empiezan en las próximas 2 horas, según el plan.</p>
          {datos.ahora_hacer.length === 0 ? (
            <p className="tenue">Nada planificado en las próximas 2 horas.</p>
          ) : (
            <table>
              <thead>
                <tr>
                  <th>Hora</th>
                  <th>Recurso</th>
                  <th>Operario</th>
                  <th>OF</th>
                  <th>Operación</th>
                  <th>Riesgo</th>
                </tr>
              </thead>
              <tbody>
                {datos.ahora_hacer.map((t) => (
                  <tr key={t.operacion_id} title={t.motivo.join(' · ')}>
                    <td className="mono">
                      {hora(t.inicio)}–{hora(t.fin)}
                    </td>
                    <td>{t.recurso}</td>
                    <td>{t.operario ?? <span className="nd">—</span>}</td>
                    <td>
                      <Link to={`/ofs/${t.of_id}`}>{t.of}</Link>
                    </td>
                    <td>
                      {t.tipo} {t.provisional && <span className="etiqueta">provisional</span>}
                    </td>
                    <td>
                      <Riesgo nivel={t.riesgo} />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
          <h2 style={{ marginTop: 16 }}>Acciones recomendadas</h2>
          {datos.acciones_recomendadas.length === 0 ? (
            <p className="tenue">Sin acciones pendientes.</p>
          ) : (
            <ul className="lista-plana">
              {datos.acciones_recomendadas.map((a, i) => (
                <li key={i}>
                  <Riesgo nivel={a.nivel} /> {a.texto}
                </li>
              ))}
            </ul>
          )}
        </section>
      </div>

      <div className="rejilla dos" style={{ marginTop: 14 }}>
        <section className="panel">
          <h2>Aparatos</h2>
          <table>
            <thead>
              <tr>
                <th>Aparato</th>
                <th>Semana</th>
                <th>Fin previsto</th>
                <th className="num">Holgura</th>
                <th className="num">Horas pend.</th>
                <th>Riesgo</th>
              </tr>
            </thead>
            <tbody>
              {datos.aparatos.map((a) => (
                <tr key={a.aparato_id} title={a.motivos.join('\n')}>
                  <td>
                    <Link to={`/aparatos/${a.aparato_id}`}>{a.referencia}</Link>
                  </td>
                  <td>{semana(a.semana)}</td>
                  <td>{fecha(a.fin_previsto)}</td>
                  <td className="num">{a.holgura_h === null ? '—' : horas(a.holgura_h)}</td>
                  <td className="num">{horas(a.horas_restantes)}</td>
                  <td>
                    <Riesgo nivel={a.nivel} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
        <section className="panel">
          <h2>Cuellos de botella</h2>
          {datos.cuellos.length === 0 ? (
            <p className="tenue">Sin recursos saturados en el horizonte.</p>
          ) : (
            <table>
              <thead>
                <tr>
                  <th>Recurso</th>
                  <th className="num">Demanda</th>
                  <th className="num">Capacidad</th>
                  <th className="num">Utilización</th>
                  <th className="num">Cola</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {datos.cuellos.map((c) => (
                  <tr key={c.recurso_id} title={c.mensaje ?? ''}>
                    <td>
                      <strong>{c.codigo}</strong> <span className="tenue pequeno">{c.nombre}</span>
                      {c.mensaje && <div className="pequeno">{c.mensaje}</div>}
                    </td>
                    <td className="num">{horas(c.demanda_h)}</td>
                    <td className="num">{horas(c.capacidad_h)}</td>
                    <td className="num">{pct(c.utilizacion)}</td>
                    <td className="num">{c.cola}</td>
                    <td>
                      <Riesgo nivel={c.nivel} />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
          {datos.maquinas_paradas.length > 0 && (
            <div className="mensaje error">
              Máquinas paradas: {datos.maquinas_paradas.map((m) => `${m.codigo} (${m.estado})`).join(', ')}
            </div>
          )}
        </section>
      </div>

      <section className="panel" style={{ marginTop: 14 }}>
        <h2>¿Qué ha cambiado?</h2>
        {datos.cambios_recientes.length === 0 ? (
          <p className="tenue">Sin cambios desde la generación del plan.</p>
        ) : (
          <TablaCambios cambios={datos.cambios_recientes} />
        )}
      </section>

      {generar && (
        <GenerarPlan
          onCerrar={() => setGenerar(false)}
          onHecho={() => {
            setGenerar(false)
            recargar()
          }}
        />
      )}
    </>
  )
}

export function TablaCambios({ cambios }: { cambios: Cambio[] }) {
  return (
    <table>
      <thead>
        <tr>
          <th>Cuándo</th>
          <th>OF</th>
          <th>ANTES</th>
          <th>DESPUÉS</th>
          <th className="num">IMPACTO</th>
          <th>MOTIVO</th>
          <th>Riesgo tanda</th>
        </tr>
      </thead>
      <tbody>
        {cambios.map((c, i) => (
          <tr key={i}>
            <td className="pequeno">
              {fecha(c.fecha)}
              {c.usuario && <div className="tenue">{c.usuario}</div>}
            </td>
            <td>
              {c.of} <span className="tenue pequeno">{c.tipo}</span>
            </td>
            <td className="pequeno">{c.antes ? `${fecha(c.antes.inicio)} · ${c.antes.recurso ?? ''}${c.antes.operario ? ' · ' + c.antes.operario : ''}` : '—'}</td>
            <td className="pequeno">{c.despues ? `${fecha(c.despues.inicio)} · ${c.despues.recurso ?? ''}${c.despues.operario ? ' · ' + c.despues.operario : ''}` : <strong>sale del plan</strong>}</td>
            <td className="num">{minutos(c.impacto_min)}</td>
            <td className="pequeno">{c.motivo}</td>
            <td>
              {c.riesgo_antes && (
                <>
                  <Riesgo nivel={c.riesgo_antes} /> → <Riesgo nivel={c.riesgo_despues ?? null} />
                </>
              )}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  )
}

function GenerarPlan({ onCerrar, onHecho }: { onCerrar: () => void; onHecho: () => void }) {
  const { datos: comprob, error } = useDatos(() => api.post<Comprobacion[]>('/plan/comprobaciones'), [])
  const [definitivo, setDefinitivo] = useState(false)
  const [nombre, setNombre] = useState('')
  const [resultado, setResultado] = useState<{ kpis: Kpis; no_planificadas: number; riesgo_tandas: RiesgoTanda[] } | null>(null)
  const [err, setErr] = useState<unknown>(null)
  const [enviando, setEnviando] = useState(false)
  const bloqueante = comprob?.some((c) => c.estado === 'BLOQUEANTE')
  return (
    <Modal titulo="Generar plan" onCerrar={resultado ? onHecho : onCerrar}>
      <p className="tenue">Antes de generar se validan datos, recursos, trabajadores, dependencias, materiales, programación y conflictos.</p>
      <MensajeError error={error} />
      {!comprob ? (
        <Cargando />
      ) : (
        <table>
          <tbody>
            {comprob.map((c) => (
              <tr key={c.paso}>
                <td style={{ width: 200 }}>
                  <strong>{c.paso}</strong>
                </td>
                <td>
                  <Riesgo nivel={c.estado === 'OK' ? 'VERDE' : c.estado === 'AVISO' ? 'AMARILLO' : 'ROJO'} /> {c.estado}
                </td>
                <td className="pequeno">{c.detalle}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {!resultado && (
        <div className="formulario" style={{ marginTop: 12 }}>
          <label className="campo">
            Nombre del plan
            <input value={nombre} onChange={(e) => setNombre(e.target.value)} placeholder="Plan del día" />
          </label>
          <label className="campo" style={{ flexDirection: 'row', alignItems: 'center', gap: 8 }}>
            <input type="checkbox" checked={definitivo} onChange={(e) => setDefinitivo(e.target.checked)} disabled={bloqueante} />
            Plan definitivo {bloqueante && <span className="riesgo ROJO">bloqueado por errores críticos</span>}
          </label>
          <button
            className="primario"
            disabled={enviando || !comprob}
            onClick={async () => {
              setEnviando(true)
              setErr(null)
              try {
                setResultado(await api.post('/plan/generar', { nombre: nombre || null, definitivo }))
              } catch (e) {
                setErr(e)
              } finally {
                setEnviando(false)
              }
            }}
          >
            {enviando ? 'Generando…' : 'Generar'}
          </button>
        </div>
      )}
      <MensajeError error={err} />
      {resultado && (
        <div className="mensaje ok">
          <strong>Plan generado.</strong> {resultado.kpis.planificadas} operaciones planificadas ({horas(resultado.kpis.horas_planificadas)}), {resultado.no_planificadas} no
          planificables, fin previsto {fecha(resultado.kpis.fin_plan)}, cumplimiento de semana {pct(resultado.kpis.cumplimiento_semana)}.
          <ul>
            {resultado.riesgo_tandas.map((t) => (
              <li key={t.tanda_id}>
                Tanda {t.numero}: <Riesgo nivel={t.nivel} /> {t.motivos[0]}
              </li>
            ))}
          </ul>
          <button onClick={onHecho}>Cerrar</button>
        </div>
      )}
    </Modal>
  )
}
