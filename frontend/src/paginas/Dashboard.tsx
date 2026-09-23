import { api } from '../api'
import { Cargando, Kpi, MensajeError, Riesgo, useDatos } from '../componentes/comunes'
import { fecha, horas, pct } from '../formato'
import type { Nivel } from '../tipos'

interface Global {
  produccion: { of_terminadas_hoy: number; of_pendientes: number; horas_previstas_pendientes: number; horas_reales_hoy: number; horas_planificadas_de_lo_fichado_hoy: number; desviacion_hoy_pct: number | null; cumplimiento_semana: number | null }
  tandas: { en_plazo: number; riesgo: number; retrasadas: number }
  aparatos: { completos: number; en_proceso: number; bloqueados: number }
  recursos: { ocupacion: { codigo: string; utilizacion: number; nivel: Nivel }[]; paradas: number; utilizacion_media: number | null }
  personal: { en_turno: number; ausentes: number; ocupados: number; disponibles: number; total: number }
  calidad: { incidencias_abiertas: number; por_tipo: Record<string, number>; retrabajos: number }
  plan: Record<string, number | string | null>
}

export default function Dashboard() {
  const { datos, error } = useDatos(() => api.get<Global>('/dashboard/global'), [], 60000)
  if (error) return <MensajeError error={error} />
  if (!datos) return <Cargando />
  const p = datos.produccion
  return (
    <>
      <div className="cabecera">
        <div>
          <h1>Indicadores</h1>
          <div className="sub">Producción, tandas, aparatos, recursos, personal y calidad. La calidad del plan se mide con varias métricas, no con una sola.</div>
        </div>
      </div>
      <h2>Producción</h2>
      <div className="kpis">
        <Kpi valor={p.of_terminadas_hoy} etiqueta="OF terminadas hoy" />
        <Kpi valor={p.of_pendientes} etiqueta="OF pendientes" />
        <Kpi valor={horas(p.horas_previstas_pendientes)} etiqueta="Horas previstas pendientes" />
        <Kpi valor={horas(p.horas_reales_hoy)} etiqueta={`Horas reales hoy (plan ${horas(p.horas_planificadas_de_lo_fichado_hoy)})`} />
        <Kpi valor={p.desviacion_hoy_pct === null ? '—' : `${p.desviacion_hoy_pct > 0 ? '+' : ''}${p.desviacion_hoy_pct}%`} etiqueta="Desviación real / previsto" />
        <Kpi valor={pct(p.cumplimiento_semana)} etiqueta="Cumplimiento de semana (plan)" nivel={p.cumplimiento_semana !== null && p.cumplimiento_semana < 1 ? 'NARANJA' : 'VERDE'} />
      </div>
      <div className="rejilla tres">
        <section className="panel">
          <h2>Tandas</h2>
          <div className="kpis">
            <Kpi valor={datos.tandas.en_plazo} etiqueta="En plazo" nivel="VERDE" />
            <Kpi valor={datos.tandas.riesgo} etiqueta="En riesgo" nivel="NARANJA" />
            <Kpi valor={datos.tandas.retrasadas} etiqueta="Retrasadas / no garantizables" nivel="ROJO" />
          </div>
        </section>
        <section className="panel">
          <h2>Aparatos</h2>
          <div className="kpis">
            <Kpi valor={datos.aparatos.completos} etiqueta="Completos" nivel="VERDE" />
            <Kpi valor={datos.aparatos.en_proceso} etiqueta="En proceso" />
            <Kpi valor={datos.aparatos.bloqueados} etiqueta="Bloqueados" nivel="ROJO" />
          </div>
        </section>
        <section className="panel">
          <h2>Personal</h2>
          <div className="kpis">
            <Kpi valor={datos.personal.disponibles} etiqueta="Disponibles" nivel="VERDE" />
            <Kpi valor={datos.personal.ocupados} etiqueta="Ocupados" />
            <Kpi valor={datos.personal.ausentes} etiqueta="Ausentes" nivel={datos.personal.ausentes ? 'AMARILLO' : undefined} />
          </div>
        </section>
      </div>
      <div className="rejilla dos" style={{ marginTop: 14 }}>
        <section className="panel">
          <h2>Recursos · ocupación prevista</h2>
          <p className="pequeno tenue">
            {datos.recursos.paradas} recursos parados · utilización media {pct(datos.recursos.utilizacion_media)}
          </p>
          <table>
            <tbody>
              {datos.recursos.ocupacion.map((r) => (
                <tr key={r.codigo}>
                  <td style={{ width: 130 }}>{r.codigo}</td>
                  <td>
                    <div className="progreso" style={{ height: 10 }}>
                      <div style={{ width: `${Math.min(100, r.utilizacion * 100)}%` }} />
                    </div>
                  </td>
                  <td className="num" style={{ width: 60 }}>
                    {pct(r.utilizacion)}
                  </td>
                  <td style={{ width: 90 }}>
                    <Riesgo nivel={r.nivel} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
        <section className="panel">
          <h2>Calidad del plan</h2>
          <table>
            <tbody>
              <tr><td>Operaciones planificadas</td><td className="num">{datos.plan.planificadas ?? '—'}</td></tr>
              <tr><td>No planificables</td><td className="num">{datos.plan.no_planificadas ?? '—'}</td></tr>
              <tr><td>Provisionales (pendientes de programa)</td><td className="num">{datos.plan.provisionales ?? '—'}</td></tr>
              <tr><td>Horas planificadas</td><td className="num">{horas(datos.plan.horas_planificadas as number)}</td></tr>
              <tr><td>Fin del plan</td><td className="num">{fecha(datos.plan.fin_plan as string)}</td></tr>
              <tr><td>Retraso total sobre semanas</td><td className="num">{horas(datos.plan.retraso_total_h as number)}</td></tr>
              <tr><td>Cambios de preparación (setup)</td><td className="num">{datos.plan.cambios_setup ?? '—'}</td></tr>
              <tr><td>Horas muertas entre trabajos</td><td className="num">{horas(datos.plan.horas_muertas as number)}</td></tr>
              <tr><td>WIP medio (OF abiertas)</td><td className="num">{datos.plan.wip_medio_of ?? '—'}</td></tr>
            </tbody>
          </table>
          <h2 style={{ marginTop: 14 }}>Calidad de fabricación</h2>
          <p>
            {datos.calidad.incidencias_abiertas} incidencias abiertas · {datos.calidad.retrabajos} de calidad (retrabajos)
          </p>
          <p className="pequeno tenue">{Object.entries(datos.calidad.por_tipo).map(([k, v]) => `${k}: ${v}`).join(' · ')}</p>
        </section>
      </div>
    </>
  )
}
