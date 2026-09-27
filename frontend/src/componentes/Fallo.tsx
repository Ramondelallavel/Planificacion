import { Component, type ErrorInfo, type ReactNode } from 'react'
import { useLocation } from 'react-router-dom'

interface Props {
  children: ReactNode
}

/** Si una pantalla falla al dibujarse, se muestra un aviso en su lugar (no una página en blanco)
 * y el resto de la aplicación sigue funcionando. */
class Barrera extends Component<Props, { error: Error | null }> {
  state = { error: null as Error | null }

  static getDerivedStateFromError(error: Error) {
    return { error }
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error('Fallo en la pantalla:', error, info.componentStack)
  }

  render() {
    const { error } = this.state
    if (!error) return this.props.children
    return (
      <div className="panel" role="alert">
        <h2>Esta pantalla ha tenido un problema</h2>
        <p>Tus datos no se han perdido. Puedes volver a intentarlo o ir a otra pantalla desde el menú.</p>
        <details>
          <summary className="pequeno">Detalle técnico</summary>
          <pre className="pequeno" style={{ whiteSpace: 'pre-wrap' }}>
            {String(error.message || error).slice(0, 2000)}
          </pre>
        </details>
        <div className="botones">
          <button className="primario" onClick={() => this.setState({ error: null })}>
            Reintentar
          </button>
          <button onClick={() => window.location.reload()}>Recargar la aplicación</button>
        </div>
      </div>
    )
  }
}

/** Cada pantalla tiene su propia barrera: al cambiar de pantalla se empieza de cero. */
export default function Fallo({ children }: Props) {
  const { pathname } = useLocation()
  return <Barrera key={pathname}>{children}</Barrera>
}
