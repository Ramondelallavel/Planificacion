import { useEffect, useRef, useState } from 'react'
import { useLocation } from 'react-router-dom'
import { comentarios, type Comentarios } from '../plataforma'

/**
 * «Pedir un cambio»: desde cualquier pantalla, escribe qué quieres cambiar o añadir y se envía
 * a Claude como comentario sobre esa pantalla (solo en la versión publicada en claude.ai).
 */
export default function PedirCambio() {
  const [api, setApi] = useState<Comentarios | null>(null)
  const [disponible, setDisponible] = useState<string>('off')
  const [abierto, setAbierto] = useState(false)
  const [texto, setTexto] = useState('')
  const [estado, setEstado] = useState<{ tipo: 'ok' | 'error' | 'aviso'; texto: string } | null>(null)
  const [enviando, setEnviando] = useState(false)
  const loc = useLocation()
  const area = useRef<HTMLTextAreaElement>(null)

  useEffect(() => {
    comentarios().then((c) => setApi(c))
  }, [])
  useEffect(() => {
    if (abierto && api) {
      api.canSendToClaude().then(setDisponible, () => setDisponible('off'))
      setTimeout(() => area.current?.focus(), 0)
    }
  }, [abierto, api])

  if (!api) return null
  const pantalla = () => {
    const h1 = document.querySelector('main h1')?.textContent?.trim()
    return `${h1 ?? 'Pantalla'} (#${loc.pathname}${loc.search})`
  }

  const enviar = async () => {
    const principal = document.querySelector('main') ?? document.body
    setEnviando(true)
    setEstado(null)
    try {
      if (disponible === 'available') {
        const anchor = await api.anchorFor(principal)
        await api.sendToClaude({ anchor, text: `[${pantalla()}]\n${texto.trim()}`.slice(0, 4000) })
        setEstado({ tipo: 'ok', texto: 'Enviado a Claude. Te responderá en el hilo de comentarios de esta página y hará el cambio.' })
        setTexto('')
      } else {
        const r = await api.openComposer({ element: principal })
        setEstado(
          r.opened
            ? { tipo: 'aviso', texto: 'Se ha abierto el comentario de claude.ai: pega tu texto y pulsa «Send to Claude».' }
            : { tipo: 'aviso', texto: 'No se pudo abrir el comentario ahora mismo. Inténtalo de nuevo con un clic.' },
        )
        if (r.opened) navigator.clipboard?.writeText(texto).catch(() => {})
      }
    } catch (e) {
      const code = (e as { code?: string }).code
      const motivo: Record<string, string> = {
        consent_required: 'Necesitas permitir que esta página comente en tu nombre (acepta el aviso de claude.ai y vuelve a enviar).',
        forbidden: 'Comentar desde la página está desactivado en esta vista.',
        claude_unavailable: 'Ahora mismo no hay una sesión de Claude escuchando esta página. Tu texto sigue aquí; inténtalo más tarde o déjalo como comentario.',
        rate_limited: 'Demasiados envíos seguidos: espera un momento.',
      }
      setEstado({ tipo: 'error', texto: motivo[code ?? ''] ?? `No se pudo enviar (${code ?? (e as Error).message}).` })
    } finally {
      setEnviando(false)
    }
  }

  return (
    <div className="pedir-cambio" data-uncommentable>
      {abierto ? (
        <div className="pedir-cambio-panel" role="dialog" aria-label="Pedir un cambio">
          <div className="cabecera-panel">
            <strong>Pedir un cambio</strong>
            <button className="cerrar" onClick={() => setAbierto(false)} aria-label="Cerrar">
              ✕
            </button>
          </div>
          <p className="pequeno tenue">
            Sobre: <em>{pantalla()}</em>
          </p>
          <textarea
            id="pedir-cambio-texto"
            ref={area}
            value={texto}
            maxLength={3800}
            onChange={(e) => setTexto(e.target.value)}
            placeholder="Qué quieres cambiar, añadir o corregir en esta pantalla…"
            rows={5}
          />
          {estado && <div className={`mensaje ${estado.tipo}`}>{estado.texto}</div>}
          <div className="botones">
            <button className="primario" disabled={enviando || !texto.trim()} onClick={enviar}>
              {disponible === 'available' ? 'Enviar a Claude' : 'Abrir comentario'}
            </button>
            {disponible !== 'available' && <span className="pequeno tenue">El envío directo a Claude no está disponible en esta vista.</span>}
          </div>
        </div>
      ) : (
        <button className="pedir-cambio-boton" onClick={() => setAbierto(true)}>
          ✎ Pedir un cambio
        </button>
      )}
    </div>
  )
}
