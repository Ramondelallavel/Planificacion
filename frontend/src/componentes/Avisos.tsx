import { useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { api } from '../api'
import { fecha } from '../formato'
import { onMotor, NAVEGADOR } from '../motor'
import { useDatos } from './comunes'

interface Aviso {
  id: number
  fecha: string
  titulo: string
  mensaje: string
  nivel: string
  leida: boolean
  referencia: string | null
}

const destino = (ref: string | null) => {
  if (!ref) return null
  const [tipo, id] = ref.split(':')
  if (tipo === 'aparato') return `/aparatos/${id}`
  if (tipo === 'incidencia') return '/incidencias'
  return null
}

/** Centro de avisos de los mandos: incidencias de planta y aparatos que pasan a riesgo rojo. */
export default function Avisos() {
  const { datos, recargar, setDatos } = useDatos(() => api.get<Aviso[]>('/notificaciones?solo_roles=true'), [], 60000)
  const [abierto, setAbierto] = useState(false)
  const caja = useRef<HTMLDivElement>(null)
  const navegar = useNavigate()

  // en la edición navegador no hay servidor que empuje: se recarga tras cada cambio
  useEffect(() => {
    if (!NAVEGADOR) return
    return onMotor((e) => {
      if (e.tipo === 'cambio') recargar()
    })
  }, [recargar])
  useEffect(() => {
    if (!abierto) return
    const fuera = (e: MouseEvent) => {
      if (caja.current && !caja.current.contains(e.target as Node)) setAbierto(false)
    }
    window.addEventListener('mousedown', fuera)
    return () => window.removeEventListener('mousedown', fuera)
  }, [abierto])

  const avisos = datos ?? []
  const sinLeer = avisos.filter((a) => !a.leida).length
  const marcar = async (a: Aviso) => {
    if (!a.leida) {
      await api.post(`/notificaciones/${a.id}/leida`)
      setDatos(avisos.map((x) => (x.id === a.id ? { ...x, leida: true } : x)))
    }
    const ruta = destino(a.referencia)
    if (ruta) {
      setAbierto(false)
      navegar(ruta)
    }
  }
  const todas = async () => {
    await api.post('/notificaciones/leidas?solo_roles=true')
    setDatos(avisos.map((x) => ({ ...x, leida: true })))
  }

  return (
    <div className="avisos" ref={caja}>
      <button className={`campana ${sinLeer ? 'con-avisos' : ''}`} onClick={() => setAbierto(!abierto)} aria-label={`Avisos: ${sinLeer} sin leer`} aria-expanded={abierto}>
        <span aria-hidden="true">🔔</span> Avisos {sinLeer > 0 && <span className="contador">{sinLeer > 99 ? '99+' : sinLeer}</span>}
      </button>
      {abierto && (
        <div className="panel-avisos" role="dialog" aria-label="Avisos">
          <div className="cabecera-avisos">
            <strong>Avisos</strong>
            {sinLeer > 0 && (
              <button className="enlace" onClick={todas}>
                Marcar todo como leído
              </button>
            )}
          </div>
          {avisos.length === 0 ? (
            <p className="tenue pequeno" style={{ padding: 12 }}>
              Sin avisos. Aquí aparecen las incidencias de planta y los aparatos que pasan a riesgo rojo.
            </p>
          ) : (
            <ul>
              {avisos.map((a) => (
                <li key={a.id} className={`${a.leida ? 'leida' : ''} ${a.nivel === 'ALERTA' ? 'alerta' : ''}`}>
                  <button onClick={() => marcar(a)}>
                    <div className="titulo-aviso">{a.titulo}</div>
                    <div className="pequeno">{a.mensaje.split('\n')[0]}</div>
                    <div className="pequeno tenue">{fecha(a.fecha)}</div>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </div>
  )
}
