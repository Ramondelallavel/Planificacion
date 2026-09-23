# Formato del PDF de tanda y cómo se interpreta

Este documento describe los formatos de hoja observados en la tanda de ejemplo **2210**
(`07_Tanda_EH-2210_OrdenesFab.pdf`, 99 páginas) y las reglas deterministas con que el sistema los
lee. La terminología es la del documento original y se conserva tal cual (OF, Grupo HF, Sección,
Orden, Destino, Pleg., Bulto, Nº Control…).

Reglas generales:

- Se lee el texto con su **posición y estilo** (negrita, cursiva, caja de cada fragmento). Las
  filas se agrupan por coordenada vertical y las columnas por el rango horizontal de su cabecera.
- Un valor que no se puede asignar a una columna, una fila que no encaja o un dato que falta
  **no se completa**: se registra una incidencia de datos con página, texto de origen y severidad.
- Los números en formato español (`1.234,5`) se convierten solo si no son ambiguos.
- Cada hoja se procesa con un contexto ligero de la hoja anterior (OF en curso, aparato, sección)
  para las continuaciones "Página 2 de 3" que no repiten la cabecera.

## Tipos de página

| Tipo | Cómo se reconoce | En la tanda 2210 |
|---|---|---|
| `HOJA_GRUPO_HF` | cabecera `TANDA` + `GRUPO HF:` | 74 páginas |
| `HOJA_CAB_PUERTAS` | lo anterior + código `Sxx-TIPO-control` (p. ej. `S40-EH-36747`) | 4 |
| `HOJA_LCH` | rótulo `Hoja de Fabricación` (con tabla `Pieza` / `Destino`) | 6 |
| `LISTA_MATERIALES` | rótulo `LISTA DE MATERIALES` | 11 |
| `PACKING_LIST` | rótulo `RELACIÓN DE BULTOS` o `PACKING LIST` | 2 |
| `SIN_TEXTO` | sin texto extraíble (se intenta OCR si está disponible) | 2 |
| `DESCONOCIDA` | nada de lo anterior → incidencia `PAGINA_NO_CLASIFICADA` con el texto | 0 |

## Cabecera común de las hojas de tanda

`TANDA`, `SECCIÓN` (código completo, p. ej. `SC000003-MF`, y abreviado `MF`), `GRUPO HF`,
`F. Emisión`, producto de la tanda y modo de fabricación (`Conjunta-Pedido`, `Serie-Conjunta`,
`Serie`, `Conjunta`, `Unitaria`).

**Semana de fabricación.** Las hojas dan la semana corta (`S40`) y la LCH la larga
(`Semana: 202640`). El año de `S40` se deriva de la **fecha de emisión** de la hoja con una regla
documentada: si la semana indicada es más de 26 semanas anterior a la semana ISO de emisión,
pertenece al año siguiente (emisión en diciembre y `S02`). Sin fecha de emisión no se deriva
(`SEMANA_NO_DERIVABLE`). Si una OF o una tanda tienen semanas distintas en distintas hojas se avisa
(`SEMANAS_DISTINTAS_EN_OF`, `SEMANAS_DISTINTAS_EN_TANDA`).

## Hoja por Grupo HF (formato estándar)

```
ORDEN 917251   EH-36747 - MONTAJE GUIA                        Conjunta-Pedido
                                              Cantidad   Sección   Orden
S40 EH - 36747
3001000/4-CONJ. GUIAS-ACCIONAM. HO   [parámetros]   1      MF      917255   ← SALIDA → OF destino
  3005100/2-ESTRIBO HO           (cursiva)          1      TPPINO  917317   ← ENTRADA ← OF que lo fabrica
  3122010/3-CONJ. CADENA ...     (cursiva)          2      MF      917200
```

Tipo de cada línea (por el **estilo** del artículo y las columnas rellenas):

| Línea | Regla | Efecto |
|---|---|---|
| `SALIDA` | artículo en letra normal/negrita con Sección/Orden | lo fabrica esta OF y va a la OF destino |
| `SALIDA_INTERNA` | destino = la propia OF | montaje interno, sin dependencia |
| `ENTRADA` | cursiva con Orden | componente que fabrica otra OF → dependencia |
| `ENTRADA_INTERNA` | cursiva con Orden = la propia OF | sin dependencia |
| `ENTRADA_COMPRA` | cursiva sin Orden | componente de compra/almacén |
| `CONSUMO_MATERIAL` | cursiva sin Orden con medida `NxL` | consumo de material (barras, chapa) |

Variantes que lee la misma rutina:

- **Serie (CIL)**: el aparato va en la misma fila que el artículo (`S40 EH- 36760 6350451/6-…`).
- **Conjunta (COR, LaserTub, FICEP, GEKA, SABI)**: título con programa
  (`PL025286/A - CORTE-TALADRO LASERTUB`), bloque `Consumidos … Total`, identificador de pieza
  (`EH-36747-0305`) y detalle de corte (`2x235`). El programa y la máquina citada se guardan en la
  OF: la máquina se usa como restricción dura al planificar.
- **Consumidos (suma)**: resumen de material al final de la OF.
- **Parámetros** junto al artículo (`PL=1000 Mano=I Acabado=0 L=983`) se guardan como pares
  clave/valor sin interpretar; un parámetro sin artículo claro → `PARAMETROS_HUERFANOS`.

## Hoja CAB de puertas batientes (`HOJA_CAB_PUERTAS`)

- **SOLD. MARCOS P. BAT.**: `S40-EH-36747  SOLD. MARCOS P. BAT.` + `ORDEN 917275` y una casilla
  gris por unidad con su recuadro de parámetros.
- **MONTAJE-EMBALAJE PUERTAS**: sin fila `ORDEN`; cada casilla trae `Orden 917194` y `Nº Bulto 6`,
  más la `BOLSA ACCESORIOS` con sus componentes (`OF_DESDE_CASILLA`).

Los recuadros de parámetros están centrados respecto a la casilla, así que una línea de parámetros
puede quedar por encima del artículo: se asigna por proximidad vertical (≤ 20 pt) y, si no, al
artículo anterior.

## Hoja de Fabricación LCH (láser de chapa)

```
SG6 | EH-36760 - SG6 NCX PUERTAS EH | Grupo Conj: SG6 NCX PUERTAS EH | Conjunta-Pedido
Semana: 202640                         ORDEN 917332
Pieza                          | Cant. | Dimensiones          | Pan. | Corte | Pleg.  | Pint. | Destino
1027-7615105/7-REFUERZO U SUP. |   1   | DC01 1,5 X 119 X 983 |      |       | 917325 |       | CAB 917280
Nº Control: 36760   PL=1000 Mano=I Acabado=0 L=983
```

- Se conserva la **posición en el nido** (`1027`), el material y las dimensiones de chapa.
- Las columnas `Pan.` / `Corte` / `Pleg.` / `Pint.` con un número de OF indican que la pieza pasa
  por esa OF antes del destino: corte LCH → plegado 917325 → CAB 917280 (dependencias `PLEGADO` y `DESTINO`).
- Una anotación no numérica bajo `Destino` (p. ej. `NO`) se guarda literal con aviso
  `ANOTACION_NO_DOCUMENTADA`: su significado no está documentado y no se interpreta.
- Flujo LCH / LaserTub: `PENDIENTE_PROGRAMACION → PROGRAMADA → LISTA_PARA_FABRICAR` en
  `estado_programacion`, y `EN_CURSO → TERMINADA` en el estado de la OF (ver
  [MODELO_DATOS.md](MODELO_DATOS.md#modelos-de-estado)).

## Lista de materiales por aparato

```
36747  LISTA DE MATERIALES  FFP 3193  Pág.1/4
Producto: ELEVADOR MONTACARGAS HO        Embalaje: NORMAL / PERSONALIZADO
Cliente: …
1 - B3001000/1 - GUIA-ACCIONAMIENTO          3365 x 510 x 545   208 kg     ← bulto
3001000/4 - CONJ. GUIAS-ACCIONAM. HO                1                     ← componente del bulto
4.1 - B3021100/1 - CAJA ACCESORIOS                  1                     ← sub-bulto de 4
    2361021/1 - ANCLAJE TORNILLO ...                10                    ← componente del sub-bulto
```

Da el árbol **APARATO → BULTO → (sub-bulto) → COMPONENTES**. La traducción al inglés que aparece
debajo de algunas líneas se guarda como `traduccion` del componente, no como otro componente. Un
bulto se enlaza con su OF cuando la hoja lo indica (casillas CAB `Orden 917194` · `Nº Bulto 6`).

## Relación de bultos / Packing list

Se extraen nº de control, cliente, su referencia, producto y bultos con dimensiones y peso, y se
cruzan con la lista de materiales (`BULTO_SOLO_EN_UNA_FUENTE` si no coinciden). **Los datos de
contacto personales del pie (teléfonos, correos) no se copian a la base de datos.**

## Grafo de dependencias entre OF

Las dependencias salen solo de los datos:

| Tipo | Origen |
|---|---|
| `COMPONENTE` | línea `ENTRADA` (cursiva con Sección/Orden): la OF de la hoja espera a la OF indicada |
| `DESTINO` | línea `SALIDA` con Orden destino: la OF destino espera a la de la hoja |
| `PLEGADO` | pieza LCH con `Pleg.` = OF |
| `REGLA_CONFIG` | reglas de ruta configuradas por la fábrica (solo si existen) |

Cada dependencia guarda sus **evidencias** (página y línea); muchas se ven desde los dos lados
(la ENTRADA en una hoja y la SALIDA en la otra). Una OF citada que no tiene hoja propia en el
documento se crea como **"referenciada sin hoja"** (`OF_REFERENCIADA_SIN_HOJA`): suele ser de otra
tanda o de una sección externa; se puede informar su fecha prevista de disponibilidad (manual,
ORTEMS o MRP) para que lo que depende de ella se planifique. Los ciclos se detectan con Tarjan y son
**críticos** (`DEPENDENCIA_CIRCULAR`): impiden el plan definitivo.

## Incidencias de datos que puede generar la ingesta

| Grupo | Códigos |
|---|---|
| Página | `PAGINA_NO_CLASIFICADA`, `PAGINA_SIN_TEXTO`, `FILA_NO_INTERPRETADA`, `VALOR_SIN_COLUMNA`, `DIMENSIONES_NO_INTERPRETADAS`, `ANOTACION_NO_DOCUMENTADA` |
| Cabecera | `TANDA_AUSENTE`, `VARIAS_TANDAS`, `SECCION_AUSENTE`, `SECCION_ABREVIADA`, `SECCION_DESCONOCIDA`, `SECCION_INCOHERENTE`, `SEMANA_AUSENTE`, `SEMANA_NO_DERIVABLE`, `SEMANAS_DISTINTAS_EN_OF`, `SEMANAS_DISTINTAS_EN_TANDA` |
| OF y líneas | `OF_SIN_NUMERO`, `OF_DUPLICADA`, `OF_SIN_LINEAS`, `OF_SIN_APARATO`, `OF_REFERENCIADA_SIN_HOJA`, `LINEA_SIN_OF`, `FILA_SIN_OF`, `CANTIDAD_AUSENTE`, `CANTIDAD_INCOHERENTE`, `PARAMETROS_HUERFANOS`, `PIEZA_SIN_DESTINO`, `RELACION_AMBIGUA`, `REFERENCIA_DUPLICADA` |
| Aparatos y bultos | `APARATO_SIN_OF`, `APARATO_SIN_BULTO`, `BULTO_SIN_PADRE`, `BULTO_SIN_DESCRIPCION`, `BULTO_SOLO_EN_UNA_FUENTE`, `COMPONENTE_SIN_BULTO`, `LISTA_SIN_CONTROL`, `PACKING_SIN_CONTROL`, `PACKING_SIN_TABLA` |
| Grafo | `DEPENDENCIA_CIRCULAR` |
| Operaciones | `OPERACION_NO_MAPEADA`, `OPERACION_SIN_RECURSO`, `SIN_TIEMPO_ESTANDAR` |
| Versiones | `OF_AUSENTE_EN_NUEVA_VERSION` |

Severidades: `CRITICA` (impide el plan definitivo), `ERROR`, `ADVERTENCIA`, `INFO`. Todas se
revisan en la pantalla del documento, donde se marcan como `REVISADA`, `RESUELTA` o `IGNORADA`
(las dos últimas exigen explicar la resolución; queda auditado).

## Resultado sobre la tanda 2210

99 páginas en 2 bloques (~1,6 s en el entorno de pruebas): 130 OF con hoja propia más 9 referenciadas sin hoja, 970
líneas, 2 aparatos, 36 bultos, 149 dependencias y ningún ciclo. Detalle y comprobaciones en
[CASOS_PRUEBA.md](CASOS_PRUEBA.md).
