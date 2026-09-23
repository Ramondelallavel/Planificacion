import { Fragment, type ReactNode } from 'react'

// Markdown mínimo para las respuestas del asistente: párrafos, títulos, listas, tablas,
// bloques de código, **negrita**, *cursiva* y `código`. Nunca se inyecta HTML.

function enLinea(txt: string): ReactNode[] {
  const partes = txt.split(/(\*\*[^*]+\*\*|`[^`]+`|\*[^*\s][^*]*\*)/g)
  return partes.map((p, i) => {
    if (p.startsWith('**') && p.endsWith('**') && p.length > 4) return <strong key={i}>{p.slice(2, -2)}</strong>
    if (p.startsWith('`') && p.endsWith('`') && p.length > 2) return <code key={i}>{p.slice(1, -1)}</code>
    if (p.startsWith('*') && p.endsWith('*') && p.length > 2) return <em key={i}>{p.slice(1, -1)}</em>
    return <Fragment key={i}>{p}</Fragment>
  })
}

const celdas = (linea: string) =>
  linea
    .trim()
    .replace(/^\|/, '')
    .replace(/\|$/, '')
    .split('|')
    .map((c) => c.trim())

export default function Markdown({ texto }: { texto: string }) {
  const lineas = texto.replace(/\r/g, '').split('\n')
  const bloques: ReactNode[] = []
  let i = 0
  while (i < lineas.length) {
    const l = lineas[i]
    if (!l.trim()) {
      i++
      continue
    }
    if (l.trim().startsWith('```')) {
      const codigo: string[] = []
      i++
      while (i < lineas.length && !lineas[i].trim().startsWith('```')) codigo.push(lineas[i++])
      i++
      bloques.push(<pre key={bloques.length}>{codigo.join('\n')}</pre>)
      continue
    }
    const titulo = /^(#{1,4})\s+(.*)$/.exec(l)
    if (titulo) {
      bloques.push(titulo[1].length <= 2 ? <h3 key={bloques.length}>{enLinea(titulo[2])}</h3> : <h4 key={bloques.length}>{enLinea(titulo[2])}</h4>)
      i++
      continue
    }
    if (l.trim().startsWith('|')) {
      const filas: string[][] = []
      while (i < lineas.length && lineas[i].trim().startsWith('|')) {
        if (!/^\s*\|?\s*:?-{2,}/.test(lineas[i])) filas.push(celdas(lineas[i]))
        i++
      }
      const [cab, ...cuerpo] = filas
      bloques.push(
        <div key={bloques.length} className="tabla-desplazable">
          <table>
            <thead>
              <tr>
                {cab.map((c, k) => (
                  <th key={k}>{enLinea(c)}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {cuerpo.map((f, k) => (
                <tr key={k}>
                  {f.map((c, j) => (
                    <td key={j}>{enLinea(c)}</td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>,
      )
      continue
    }
    const vineta = /^\s*[-*•]\s+/
    const numero = /^\s*\d+[.)]\s+/
    if (vineta.test(l) || numero.test(l)) {
      const ordenada = numero.test(l)
      const patron = ordenada ? numero : vineta
      const items: string[] = []
      while (i < lineas.length && patron.test(lineas[i])) items.push(lineas[i++].replace(patron, ''))
      const lista = items.map((t, k) => <li key={k}>{enLinea(t)}</li>)
      bloques.push(ordenada ? <ol key={bloques.length}>{lista}</ol> : <ul key={bloques.length}>{lista}</ul>)
      continue
    }
    const parrafo: string[] = []
    while (i < lineas.length && lineas[i].trim() && !/^(#{1,4}\s|\s*[-*•]\s|\s*\d+[.)]\s|\s*\||```)/.test(lineas[i])) parrafo.push(lineas[i++])
    if (!parrafo.length) parrafo.push(lineas[i++])
    bloques.push(
      <p key={bloques.length}>
        {parrafo.map((t, k) => (
          <Fragment key={k}>
            {k > 0 && <br />}
            {enLinea(t)}
          </Fragment>
        ))}
      </p>,
    )
  }
  return <div className="markdown">{bloques}</div>
}
