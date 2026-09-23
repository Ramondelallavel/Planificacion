# Casos de prueba

```bash
cd backend
python -m pytest                        # 40 pruebas; SQLite temporal por prueba
HIDRAL_TEST_DB_URL=postgresql+psycopg://usuario@host/bd_pruebas python -m pytest   # misma batería en PostgreSQL (vacía esa base)
```

Las pruebas no dependen de datos reales: `tests/generador_pdf.py` genera PDF sintéticos con la misma
maquetación que las hojas de HIDRAL (cabeceras, columnas, cursivas, LCH, CAB, lista de materiales,
relación de bultos) y con variantes para forzar errores: fila sin cantidad, relación ambigua,
sección desconocida, OF duplicada, dependencia circular, embalaje omitido, cantidades distintas…

Toda prueba que planifica comprueba además, con un verificador **independiente** del programador
(`plan_valido` en `conftest.py`), que el plan no viola ninguna restricción dura: sin solapes por
recurso u operario, precedencias respetadas, dentro de turno, recurso y operario capaces.

La fábrica usada es la de ejemplo (`config/fabrica_ejemplo.yaml`) y el reloj está fijado en el
lunes 21/09/2026 07:00 (la semana objetivo 202640 vence el viernes 02/10).

## Casos obligatorios A–P (`tests/test_casos_obligatorios.py`)

| Caso | Prueba | Qué se comprueba |
|---|---|---|
| A · B · C | `test_casos_A_B_C_tanda_con_n_aparatos[1, 2, 4]` | tandas con 1, 2 y 4 aparatos: aparatos, OF, OF sin hoja, dependencias, 3 bultos por aparato, semana 202640, sin críticas y plan válido |
| D | `test_caso_D_tanda_de_600_paginas_por_bloques` | 600 páginas y 30 aparatos procesados en varios bloques, pico de memoria Python < 200 MB (tracemalloc), < 180 s, todas las OF presentes |
| E | `test_caso_E_dos_tandas_con_recursos_compartidos` | dos tandas en el mismo plan, recursos compartidos sin solapes, riesgo por tanda |
| F | `test_caso_F_maquina_averiada_replanifica_solo_la_zona_afectada` | avería de LaserTub: solo cambian algunas operaciones, nada en la máquina durante la avería, motivo en cada cambio, riesgo antes/después |
| G | `test_caso_G_trabajador_ausente` | ausencia de 48 h: sus trabajos pasan a otro operario cualificado o después de la ausencia |
| H | `test_caso_H_falta_de_material` | sin material ni fecha no se planifica (`ESPERANDO_MATERIAL`, sucesoras `PREDECESORA_NO_PLANIFICABLE`); con fecha, se planifica a partir de ella |
| I | `test_caso_I_of_urgente_simular_rechazar_aceptar` | texto "Introducir esta OF ahora provocaría…", rechazar deja el plan intacto, aceptar crea plan nuevo válido con la OF urgente |
| J | `test_caso_J_operacion_pendiente_de_programacion` | operación `PROGRAMACION` antes del corte, corte provisional; no se puede fichar hasta registrar el programa; después `LISTA_PARA_FABRICAR` y se ficha |
| K | `test_caso_K_lch` | piezas de chapa con posición, material y dimensiones; OF de plegado referenciada sin hoja; cadena corte → plegado → destino |
| L | `test_caso_L_lasertub` | programa `PL025286/A`, estado `PROGRAMADA`, operación `CORTE_TALADRO` asignada a LASERTUB con explicación "programa" |
| M | `test_caso_M_of_con_dependencia_pendiente` | no se puede iniciar con la predecesora sin terminar; un responsable (jefe de equipo) puede autorizarlo y queda registrado |
| N | `test_caso_N_datos_ambiguos` | cantidad ausente (`CANTIDAD_AUSENTE`, cantidad nula), relación ambigua con 2 alternativas, sección desconocida, OF duplicada `CRITICA`; plan definitivo bloqueado, provisional permitido |
| O | `test_caso_O_pdf_duplicado` | mismo fichero dos veces: se detecta por hash y no se crea otro documento ni trabajo |
| P | `test_caso_P_nueva_version_del_mismo_pdf` | nueva versión: la anterior `SUSTITUIDO`, OF actualizadas sin duplicar líneas, OF desaparecidas señaladas (`OF_AUSENTE_EN_NUEVA_VERSION`) |
| — | `test_dependencia_circular_es_critica` | ciclo detectado como `CRITICA`, comprobación previa `BLOQUEANTE`, operaciones del ciclo no planificadas |
| — | `test_procesamiento_asincrono_devuelve_inmediatamente` | la carga devuelve el trabajo en cola al instante y el trabajador lo completa |

## Tanda real 2210 (`tests/test_pdf_real.py`)

Se ejecutan si `backend/tests/fixtures/07_Tanda_EH-2210_OrdenesFab.pdf` existe (o la ruta de
`HIDRAL_PDF_EJEMPLO`); el PDF **no se versiona** porque contiene datos de cliente.

| Prueba | Qué se comprueba |
|---|---|
| `test_estructura_de_la_tanda_2210` | 99 páginas, tanda 2210 `EH/DC-5000 \| HO` semana 202640, 130 OF con hoja, aparatos EH-36747 y EH-36760, recuento exacto por tipo de página, ninguna fila sin interpretar, sin críticas ni ciclos |
| `test_of_917251_montaje_guia` | sección MF, grupo HF, modo, aparato, predecesoras 917317 y 917200, sucesora 917255, parámetros de la salida y trazabilidad a la página 1 |
| `test_lch_y_plegado` | OF 917332: 18 piezas de chapa, pendiente de programación, cadena por plegado 917325 hacia 917280 |
| `test_lasertub_y_consumos` | OF 917245: programa y máquina LASERTUB, consumos con total, detalle de corte `2x235` |
| `test_bultos_de_lista_de_materiales_packing_y_cab` | 36 bultos, bulto 6 con OF 917194 confirmado por hoja CAB, lista de materiales y packing list; más de 250 componentes |
| `test_plan_sobre_la_tanda_real` | más de 100 operaciones planificadas y plan válido; 917217 `SIN_RECURSO` (sección sin configurar) y 917252 bloqueada por ella; al informar una fecha de disponibilidad externa deja de estar bloqueada |

## API y servicios (`tests/test_api_y_servicios.py`)

| Prueba | Qué se comprueba |
|---|---|
| `test_flujo_api_completo` | sin sesión no hay acceso; carga (202 y progreso al 100 %), plan, Control Tower, Gantt, explicación de una asignación (motivos de prioridad y recurso), movimiento a un sábado rechazado con motivos y auditado, indicadores y plan por turno |
| `test_permisos_por_rol` | cada rol solo accede a lo suyo |
| `test_movimiento_manual_valido_propaga_sucesoras` | un cambio válido se aplica, se bloquea y empuja a las sucesoras |
| `test_integraciones_csv` | ORTEMS manda en la semana y registra la discrepancia; MRP en el material |
| `test_aprendizaje_propone_y_requiere_aprobacion` | propone con muestras suficientes, no aplica sin aprobar, aprobar crea versión y revertir la deshace |
| `test_reanudacion_tras_caida` | un trabajo interrumpido continúa desde su último bloque sin duplicar datos |
| `test_what_if_no_modifica_el_plan_real` | el simulador no toca el plan oficial |
| `test_what_if_incremental_conserva_lo_que_ya_no_era_planificable` | en una simulación incremental, lo que ya no era planificable sigue sin serlo: una avería no puede mejorar el cumplimiento |

Además, `tests/test_unitarios.py` cubre números en formato español, parámetros, semana desde `S40`,
ventanas de turno con pausas y fin de semana, reparto de operaciones entre turnos, paradas,
ocupación y seguridad (hash de contraseñas y tokens).

## Resultados de referencia

- 40 pruebas superadas en SQLite y en PostgreSQL 16.
- Tanda 2210: 99 páginas en 2 bloques (~1,6 s en el entorno de pruebas), 130 OF con hoja propia más
  9 referenciadas sin hoja, 970 líneas, 2 aparatos, 36 bultos, 149 dependencias, 0 ciclos. Con la fábrica de
  ejemplo: 140 operaciones planificadas y 8 no planificables, todas explicadas (sección `PLPINO`
  sin recursos y lo que depende de ella).
