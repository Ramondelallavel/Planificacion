import { useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { api } from '../api'

interface Resultado {
  tipo: string
  titulo: string
  sub: string | null
  ruta: string
}

/** Búsqueda global (Ctrl+K): OF, tandas, aparatos, artículos, máquinas y operarios. */
export default function Buscador() {
  const [q, setQ] = useState('')
  const [res, setRes] = useState<Resultado[]>([])
  const [activo, setActivo] = useState(0)
  const [abierto, setAbierto] = useState(false)
  const entrada = useRef<HTMLInputElement>(null)
  const navegar = useNavigate()

  useEffect(() => {
    const atajo = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'k') {
        e.preventDefault()
        entrada.current?.focus()
        entrada.current?.select()
      }
    }
    window.addEventListener('keydown', atajo)
    return () => window.removeEventListener('keydown', atajo)
  }, [])

  useEffect(() => {
    if (q.trim().length < 2) {
      setRes([])
      return
    }
    let vigente = true
    const t = setTimeout(() => {
      api.get<Resultado[]>(`/buscar?q=${encodeURIComponent(q.trim())}`).then(
        (r) => {
          if (vigente) {
            setRes(r)
            setActivo(0)
          }
        },
        () => vigente && setRes([]),
      )
    }, 180)
    return () => {
      vigente = false
      clearTimeout(t)
    }
  }, [q])

  const ir = (r: Resultado) => {
    navegar(r.ruta)
    setAbierto(false)
    setQ('')
    entrada.current?.blur()
  }

  return (
    <div className="buscador">
      <input
        id="buscador-global"
        ref={entrada}
        type="search"
        value={q}
        placeholder="Buscar… (Ctrl+K)"
        aria-label="Buscar OF, tanda, aparato, artículo, máquina u operario"
        onChange={(e) => {
          setQ(e.target.value)
          setAbierto(true)
        }}
        onFocus={() => setAbierto(true)}
        onBlur={() => setTimeout(() => setAbierto(false), 150)}
        onKeyDown={(e) => {
          if (e.key === 'ArrowDown') setActivo((a) => Math.min(a + 1, res.length - 1))
          else if (e.key === 'ArrowUp') setActivo((a) => Math.max(a - 1, 0))
          else if (e.key === 'Enter' && res[activo]) ir(res[activo])
          else if (e.key === 'Escape') entrada.current?.blur()
        }}
      />
      {abierto && q.trim().length >= 2 && (
        <div className="buscador-resultados" role="listbox">
          {res.length === 0 ? (
            <div className="buscador-vacio">Sin resultados para «{q.trim()}»</div>
          ) : (
            res.map((r, i) => (
              <button key={`${r.ruta}-${i}`} role="option" aria-selected={i === activo} className={i === activo ? 'activo' : ''} onMouseDown={() => ir(r)}>
                <span className="etiqueta">{r.tipo}</span> <strong>{r.titulo}</strong>
                {r.sub && <div className="pequeno tenue">{r.sub}</div>}
              </button>
            ))
          )}
        </div>
      )}
    </div>
  )
}
