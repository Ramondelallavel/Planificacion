import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import App from './App'
import Arranque from './Arranque'
import { NAVEGADOR } from './motor'
import './estilos.css'

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    {NAVEGADOR ? (
      <Arranque>
        <App />
      </Arranque>
    ) : (
      <App />
    )}
  </StrictMode>,
)
