import { createContext, useContext, useEffect, useRef, useState } from 'react'
import { BrowserRouter, HashRouter, Navigate, NavLink, Route, Routes } from 'react-router-dom'
import { guardarSesion, onSesionCaducada, puede, sesionGuardada, type Sesion } from './api'
import PedirCambio from './componentes/PedirCambio'
import { NAVEGADOR, onMotor } from './motor'
import Datos from './paginas/Datos'
import { guardarEnNube } from './plataforma'
import Aparato from './paginas/Aparato'
import Auditoria from './paginas/Auditoria'
import Configuracion from './paginas/Configuracion'
import ControlTower from './paginas/ControlTower'
import Documento from './paginas/Documento'
import Importacion from './paginas/Importacion'
import Incidencias from './paginas/Incidencias'
import Login from './paginas/Login'
import OF from './paginas/OF'
import Operario from './paginas/Operario'
import PlanGantt from './paginas/PlanGantt'
import PlanTurnos from './paginas/PlanTurnos'
import Simulacion from './paginas/Simulacion'
import Tanda from './paginas/Tanda'
import Tandas from './paginas/Tandas'
import TablaOFs from './paginas/TablaOFs'
import Dashboard from './paginas/Dashboard'

interface ContextoSesion {
  sesion: Sesion | null
  salir: () => void
}

const Ctx = createContext<ContextoSesion>({ sesion: null, salir: () => {} })
export const useSesion = () => useContext(Ctx)

const ROL_TEXTO: Record<string, string> = {
  ADMINISTRADOR: 'Administrador',
  PLANIFICADOR: 'Planificador',
  JEFE_EQUIPO: 'Jefe de equipo',
  OPERARIO: 'Operario',
  SUPERVISOR: 'Supervisor',
  CONSULTA: 'Consulta',
}

// En la edición navegador la página vive dentro de un marco: rutas en el hash, sin servidor.
const Enrutador = NAVEGADOR ? HashRouter : BrowserRouter

/** Edición navegador: tras cada cambio, una copia en la nube de la página (agrupada, cada pocos minutos). */
function useCopiaAutomatica(activa: boolean) {
  const [estado, setEstado] = useState<string>('')
  const temporizador = useRef<number | undefined>(undefined)
  useEffect(() => {
    if (!activa) return
    const programar = () => {
      window.clearTimeout(temporizador.current)
      temporizador.current = window.setTimeout(() => {
        guardarEnNube().then(
          (c) => setEstado(`Copia en la nube ${new Date(c.fecha).toLocaleTimeString('es-ES', { hour: '2-digit', minute: '2-digit' })}`),
          () => setEstado(''),
        )
      }, 3 * 60 * 1000)
    }
    const quitar = onMotor((e) => {
      if (e.tipo === 'cambio') {
        setEstado('Cambios guardados en este navegador')
        programar()
      }
    })
    return () => {
      quitar()
      window.clearTimeout(temporizador.current)
    }
  }, [activa])
  return estado
}

export default function App() {
  const [sesion, setSesion] = useState<Sesion | null>(sesionGuardada())
  useEffect(() => onSesionCaducada(() => setSesion(null)), [])
  const estadoCopia = useCopiaAutomatica(NAVEGADOR && !!sesion && puede(sesion, 'configurar'))
  const salir = () => {
    guardarSesion(null)
    setSesion(null)
  }
  if (!sesion)
    return (
      <Login
        onEntrar={(s) => {
          guardarSesion(s)
          setSesion(s)
        }}
      />
    )
  const esOperario = sesion.rol === 'OPERARIO'
  const ver = puede(sesion, 'ver')
  return (
    <Ctx.Provider value={{ sesion, salir }}>
      <Enrutador>
        <div className="app">
          <aside className="lateral">
            <div className="marca">
              HIDRAL
              <small>Planificación y control de fabricación</small>
            </div>
            <nav>
              {ver && (
                <>
                  <div className="seccion-nav">Control</div>
                  <NavLink to="/">Control Tower</NavLink>
                  <NavLink to="/indicadores">Indicadores</NavLink>
                  <NavLink to="/gantt">Plan · Gantt</NavLink>
                  <NavLink to="/turnos">Plan por turno</NavLink>
                  <NavLink to="/incidencias">Incidencias</NavLink>
                  <NavLink to="/simulacion">Simulación / OF urgente</NavLink>
                  <div className="seccion-nav">Fabricación</div>
                  <NavLink to="/tandas">Tandas y aparatos</NavLink>
                  <NavLink to="/ofs">Órdenes de fabricación</NavLink>
                  <NavLink to="/importacion">Importar documentos</NavLink>
                </>
              )}
              <div className="seccion-nav">Planta</div>
              <NavLink to="/operario">{esOperario ? 'Mi trabajo' : 'Pantalla de operario'}</NavLink>
              {ver && (
                <>
                  <div className="seccion-nav">Sistema</div>
                  <NavLink to="/configuracion">Configuración de fábrica</NavLink>
                  <NavLink to="/auditoria">Auditoría</NavLink>
                  {NAVEGADOR && <NavLink to="/datos">Datos y copias</NavLink>}
                </>
              )}
            </nav>
            <div className="pie">
              <div>
                <strong>{sesion.nombre}</strong>
              </div>
              <div>{ROL_TEXTO[sesion.rol] ?? sesion.rol}</div>
              <button onClick={salir} style={{ marginTop: 8 }}>
                Salir
              </button>
              {estadoCopia && <div className="estado-copia">{estadoCopia}</div>}
            </div>
          </aside>
          <main className="contenido">
            <Routes>
              {ver ? (
                <>
                  <Route path="/" element={<ControlTower />} />
                  <Route path="/indicadores" element={<Dashboard />} />
                  <Route path="/gantt" element={<PlanGantt />} />
                  <Route path="/turnos" element={<PlanTurnos />} />
                  <Route path="/incidencias" element={<Incidencias />} />
                  <Route path="/simulacion" element={<Simulacion />} />
                  <Route path="/tandas" element={<Tandas />} />
                  <Route path="/tandas/:id" element={<Tanda />} />
                  <Route path="/aparatos/:id" element={<Aparato />} />
                  <Route path="/ofs" element={<TablaOFs />} />
                  <Route path="/ofs/:id" element={<OF />} />
                  <Route path="/importacion" element={<Importacion />} />
                  <Route path="/documentos/:id" element={<Documento />} />
                  <Route path="/configuracion" element={<Configuracion />} />
                  <Route path="/auditoria" element={<Auditoria />} />
                  {NAVEGADOR && <Route path="/datos" element={<Datos />} />}
                </>
              ) : (
                <Route path="/" element={<Navigate to="/operario" replace />} />
              )}
              <Route path="/operario" element={<Operario />} />
              <Route path="*" element={<Navigate to={ver ? '/' : '/operario'} replace />} />
            </Routes>
          </main>
          {NAVEGADOR && <PedirCambio />}
        </div>
      </Enrutador>
    </Ctx.Provider>
  )
}
