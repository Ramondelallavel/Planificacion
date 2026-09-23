# Modelo de datos

Base relacional normalizada (SQLAlchemy 2.0). En producción PostgreSQL; SQLite en desarrollo y
pruebas. El esquema se crea al arrancar (`crear_tablas()`); no hay migraciones versionadas.

## Jerarquía principal

```
Documento ──< PaginaDocumento
    │    └──< TrabajoProcesamiento (cola, checkpoint, progreso)
    │
    └── Tanda ──< Aparato ──< Bulto ──< ComponenteBulto
                    │  (N:M OFAparato)       └─ padre_id (sub-bultos)
                    └──────────── OrdenFabricacion ──< LineaOF
                                   │   ├──< Operacion ──> Recurso / TiempoEstandar
                                   │   └── ProgramaCNC
                                   └──< DependenciaOF (predecesora → sucesora, con evidencias)

Plan ──< AsignacionPlan (operación · recurso · operario · tramos · explicación · bloqueada · provisional)
     └──< CambioPlan    (ANTES / DESPUÉS / MOTIVO / IMPACTO / RIESGO, agrupados por lote)

Seccion ──< Recurso ──< ParadaRecurso          Turno · Festivo
Operario ──< Cualificacion, Ausencia           TiempoEstandar (versionado) · ReglaDependencia
Fichaje · IncidenciaProduccion · Notificacion · EstimacionPropuesta
IncidenciaDatos · Origen (trazabilidad por campo) · Auditoria · Usuario · ParametroConfig (versionado)
```

- Una OF puede servir a **varios aparatos** (`of_aparato`), como las OF de corte conjuntas.
- Las OF citadas sin hoja propia existen con `tiene_hoja = false` y pueden llevar
  `disponible_prevista` (y `fuente_disponible`) para planificar lo que depende de ellas.
- `Origen` guarda, por entidad y campo, qué sistema dio el valor (PDF, ORTEMS, MRP, TEAMCENTER,
  usuario, configuración, derivado, aprendizaje) y el detalle (página, fila).
- `IncidenciaDatos` guarda severidad, página, entidad, texto de origen y las alternativas cuando
  hay ambigüedad; su revisión queda en `resolucion` y `resuelta_por`.

## Modelos de estado

**Documento**: `EN_COLA → PROCESANDO → COMPLETADO | COMPLETADO_CON_ERRORES | ERROR`;
`DUPLICADO` (mismo hash, no se procesa); `SUSTITUIDO` (hay una versión más reciente).

**Trabajo de procesamiento**: `EN_COLA → PROCESANDO → COMPLETADO | ERROR | CANCELADO`. Un trabajo
`PROCESANDO` con el latido caducado se vuelve a reclamar y continúa desde su último bloque.

**OF** (`orden_fabricacion.estado`):

```
NO_INICIADA ─┬─> ESPERANDO_PROGRAMACION ──(programa registrado)──> LISTA
             ├─> ESPERANDO_MATERIAL
             └─> PLANIFICADA ──(primer fichaje)──> EN_CURSO <──> PAUSADA
                                                       └──(todas sus operaciones terminadas)──> TERMINADA
```

El bloqueo manual de una OF es el indicador `bloqueada_manual` (no un estado) y la urgencia el
indicador `urgente`. Los valores `VALIDADA`, `BLOQUEADA`, `INCIDENCIA` y `ESPERANDO_RECURSO` están
definidos en el enumerado pero esta versión no los asigna.

**Programación CNC** (`orden_fabricacion.estado_programacion`, flujo LCH / LaserTub):

```
NO_REQUIERE
PENDIENTE_PROGRAMACION ──(registrar programa)──> LISTA_PARA_FABRICAR
PROGRAMADA (el PDF ya trae el programa) ───────────────^
```
Mientras está pendiente, sus operaciones de máquina se planifican como **provisionales** detrás de
la operación `PROGRAMACION`.

**Operación**: `PENDIENTE | PENDIENTE_PROGRAMACION → LISTA → PLANIFICADA → EN_CURSO <-> PAUSADA → TERMINADA`
(un fin parcial la devuelve a `PENDIENTE` con `cantidad_hecha` acumulada).

**Fichaje**: `ABIERTO <-> PAUSADO → CERRADO`, con minutos de pausa, duración planificada y real y
`forzado_por` si un responsable autorizó saltar un bloqueo blando.

**Plan**: `OFICIAL` · `ACTIVO → ARCHIVADO` al generar o aceptar otro. `SIMULACION` · `BORRADOR →
DESCARTADO` (rechazada) o, si se acepta, se crea un plan `ACTIVO` y el anterior pasa a `ARCHIVADO`.

**Recurso**: `OPERATIVO | AVERIADO | MANTENIMIENTO | PARADO`; las paradas con fechas están en
`parada_recurso` (una avería registrada crea su parada y al cerrar la incidencia se cierra).

**Incidencia de datos**: `ABIERTA → REVISADA | RESUELTA | IGNORADA`.
**Incidencia de producción**: `ABIERTA → CERRADA`.
**Propuesta de aprendizaje**: `PROPUESTA → APROBADA | RECHAZADA` (aprobar crea nueva versión de
`tiempo_estandar`; revertir reactiva la anterior).

**Riesgo** (OF, aparato, tanda): `VERDE < AMARILLO < NARANJA < ROJO`, con puntuación y motivos.

## Tablas

Listado generado a partir de los modelos (`hidral_plan/modelos`). En negrita la clave primaria;
`→` indica clave ajena.

### Documentos y procesamiento

- `documento`: **id** · nombre · hash_sha256 · tamano_bytes · num_paginas · fecha_carga · usuario_carga · estado · clave_logica · version · documento_anterior_id → documento · ruta_almacen · resumen · fecha_fin
  <br>*índices: (clave_logica); (estado); (hash_sha256)*
- `pagina_documento`: **id** · documento_id → documento · numero · bloque · tipo · metodo_extraccion · num_caracteres · seccion_codigo · grupo_hf · pagina_de · ofs_detectadas · avisos · texto
  <br>*índices: (documento_id, numero); (tipo)*
- `trabajo_procesamiento`: **id** · documento_id → documento · tipo · estado · paginas_totales · paginas_procesadas · bloque_actual · bloques_totales · tamano_bloque · contadores · fase · creado · inicio · fin · latido · eta_segundos · intentos · trabajador · mensaje_error
  <br>*índices: (documento_id); (estado)*

### Estructura de fabricación

- `tanda`: **id** · numero · producto · semana_codigo · fecha_creacion · estado · prioridad · prioridad_manual · carga_total_h · carga_restante_h · progreso · riesgo_nivel · riesgo_puntuacion · riesgo_motivos · documento_id → documento · incluida_en_plan
  <br>*índices: (estado); (numero); (prioridad); (riesgo_nivel); (semana_codigo)*
- `aparato`: **id** · tanda_id → tanda · referencia · numero_control · tipo · producto · cliente · su_referencia · ffp · embalaje · extracomunitario · semana_codigo · estado · carga_estimada_h · carga_restante_h · progreso · riesgo_nivel · riesgo_motivos · fin_previsto
  <br>*únicos: (tanda_id, numero_control) — índices: (estado); (numero_control); (referencia); (riesgo_nivel); (semana_codigo); (tanda_id)*
- `bulto`: **id** · aparato_id → aparato · padre_id → bulto · numero · orden · codigo · descripcion · largo_mm · ancho_mm · alto_mm · peso_kg · estado · of_id → orden_fabricacion · fuentes
  <br>*únicos: (aparato_id, numero) — índices: (aparato_id)*
- `componente_bulto`: **id** · bulto_id → bulto · articulo_codigo · descripcion · parametros · traduccion · cantidad · pagina · of_numero
  <br>*índices: (articulo_codigo); (bulto_id)*
- `of_aparato`: **of_id** → orden_fabricacion · **aparato_id** → aparato · lineas
  <br>*índices: (aparato_id)*
- `orden_fabricacion`: **id** · numero · tanda_id → tanda · aparato_id → aparato · seccion_codigo · seccion_completa · grupo_hf · grupo_conj · descripcion · modo · programa_codigo · programa_descripcion · cantidad_total · semana_codigo · estado · estado_programacion · prioridad · prioridad_ortems · urgente · bloqueada_manual · material_disponible · material_disponible_desde · disponible_prevista · fuente_disponible · horas_estimadas · horas_reales · fecha_prevista_inicio · fecha_prevista_fin · fecha_real_inicio · fecha_real_fin · recurso_requerido · tiene_hoja · riesgo_nivel · fuente · documento_id → documento · paginas · consumos · parametros_extra
  <br>*índices: (aparato_id); (documento_id); (estado); (fecha_prevista_fin); (fecha_prevista_inicio); (grupo_hf); (numero); (prioridad); (riesgo_nivel); (seccion_codigo); (seccion_codigo, estado); (semana_codigo); (tanda_id); (tanda_id, estado)*
- `linea_of`: **id** · of_id → orden_fabricacion · tipo · articulo_codigo · articulo_descripcion · posicion · id_pieza · parametros · parametros_dict · cantidad · cantidad_texto · detalle_corte · material · espesor_mm · largo_mm · ancho_mm · aparato_id → aparato · numero_control · semana_codigo · seccion_ref · orden_ref · orden_plegado · operaciones_marcadas · pagina · texto_origen
  <br>*índices: (aparato_id); (articulo_codigo); (of_id); (orden_ref); (tipo)*
- `operacion`: **id** · of_id → orden_fabricacion · secuencia · tipo · descripcion · seccion_codigo · recurso_preferido · duracion_estimada_min · duracion_real_min · origen_duracion · tiempo_estandar_id → tiempo_estandar · estado · requiere_programa · operacion_anterior_id → operacion · cantidad · cantidad_hecha · fuente · familia_setup
  <br>*índices: (estado); (of_id); (seccion_codigo)*
- `dependencia_of`: **id** · of_origen_id → orden_fabricacion · of_destino_id → orden_fabricacion · tipo · evidencias · fuente · activa
  <br>*únicos: (of_origen_id, of_destino_id) — índices: (of_destino_id); (of_origen_id)*
- `articulo`: **codigo** · codigo_base · revision · descripcion · fuente · datos_tecnicos · actualizado
  <br>*índices: (codigo_base)*
- `programa_cnc`: **id** · codigo · of_id → orden_fabricacion · recurso_codigo · estado · fuente · registrado · registrado_por · notas
  <br>*índices: (codigo); (of_id)*

### Fábrica: recursos, personas y tiempos

- `seccion`: **codigo** · codigo_completo · nombre · flujo · requiere_programacion · conocida · fuente
- `recurso`: **id** · codigo · nombre · tipo · seccion_codigo → seccion · capacidad · estado · operaciones · alias · grupos_hf · turnos · requiere_operario · restricciones · activo · fuente
  <br>*índices: (codigo); (estado); (seccion_codigo)*
- `parada_recurso`: **id** · recurso_id → recurso · inicio · fin · motivo · incidencia_id → incidencia_produccion
  <br>*índices: (inicio); (recurso_id)*
- `turno`: **codigo** · nombre · hora_inicio · hora_fin · dias_semana · pausas · activo
- `festivo`: **fecha** · descripcion
- `operario`: **id** · codigo_empleado · nombre · turno_codigo → turno · seccion_codigo · activo
  <br>*índices: (codigo_empleado)*
- `cualificacion`: **id** · operario_id → operario · recurso_codigo · tipo_operacion · nivel · vigente_hasta
  <br>*índices: (operario_id)*
- `ausencia`: **id** · operario_id → operario · inicio · fin · motivo · incidencia_id → incidencia_produccion
  <br>*índices: (inicio); (operario_id)*
- `tiempo_estandar`: **id** · seccion_codigo · grupo_hf · articulo_codigo · tipo_operacion · minutos_preparacion · minutos_por_unidad · minutos_por_linea · fuente · es_ejemplo · version · vigente · creado · creado_por · notas
  <br>*índices: (seccion_codigo); (vigente)*
- `regla_dependencia`: **id** · grupo_hf_origen · grupo_hf_destino · mismo_aparato · descripcion · es_ejemplo · activa

### Plan

- `plan`: **id** · nombre · tipo · estado · creado · creado_por · ahora_referencia · horizonte_fin · configuracion · kpis · riesgos · no_planificadas · comprobaciones · plan_base_id → plan · escenario · motivo · definitivo
  <br>*índices: (estado); (tipo)*
- `asignacion_plan`: **id** · plan_id → plan · operacion_id → operacion · of_id → orden_fabricacion · recurso_id → recurso · unidad · operario_id → operario · inicio · fin · segmentos · minutos · prioridad · bloqueada · provisional · explicacion
  <br>*índices: (fin); (inicio); (of_id); (operacion_id); (operario_id); (plan_id); (plan_id, operario_id, inicio); (plan_id, recurso_id, inicio); (recurso_id)*
- `cambio_plan`: **id** · plan_id → plan · lote · fecha · usuario · tipo · operacion_id → operacion · of_numero · antes · despues · impacto_min · motivo · riesgo_antes · riesgo_despues
  <br>*índices: (fecha); (lote); (of_numero); (plan_id)*

### Ejecución

- `fichaje`: **id** · operario_id → operario · of_id → orden_fabricacion · operacion_id → operacion · recurso_id → recurso · inicio · fin · pausas · minutos_pausa · duracion_real_min · duracion_planificada_min · cantidad · estado · incidencia_id → incidencia_produccion · forzado_por
  <br>*índices: (estado); (inicio); (of_id); (operacion_id); (operario_id); (recurso_id)*
- `incidencia_produccion`: **id** · tipo · descripcion · recurso_id → recurso · operario_id → operario · of_id → orden_fabricacion · operacion_id → operacion · inicio · fin_prevista · fin · estado · severidad · reportado_por · lote_replanificacion · impacto
  <br>*índices: (estado); (inicio); (tipo)*
- `notificacion`: **id** · fecha · operario_id → operario · rol_destino · titulo · mensaje · nivel · leida · referencia
  <br>*índices: (fecha); (operario_id)*
- `estimacion_propuesta`: **id** · tiempo_estandar_id → tiempo_estandar · muestras · ratio_real_planificado · minutos_por_unidad_actual · minutos_por_unidad_propuesto · explicacion · estado · creada · decidida_por · decidida
  <br>*índices: (estado); (tiempo_estandar_id)*

### Calidad de datos y trazabilidad

- `incidencia_datos`: **id** · documento_id → documento · pagina · tipo · severidad · mensaje · entidad_tipo · entidad_ref · texto_origen · alternativas · estado · creada · resuelta_por · resolucion
  <br>*índices: (documento_id); (documento_id, severidad); (entidad_ref); (estado); (severidad); (tipo)*
- `origen`: **id** · entidad_tipo · entidad_id · campo · fuente · documento_id → documento · pagina · bloque · texto_origen · detalle · fecha
  <br>*índices: (documento_id); (entidad_tipo, entidad_id)*

### Seguridad y configuración

- `usuario`: **id** · usuario · nombre · rol · hash_clave · activo · operario_id → operario · creado
  <br>*índices: (usuario)*
- `auditoria`: **id** · fecha · usuario · accion · entidad_tipo · entidad_id · antes · despues · motivo · automatica
  <br>*índices: (accion); (entidad_id); (entidad_tipo); (fecha); (usuario)*
- `parametro_config`: **clave** · valor · version · actualizado · actualizado_por · descripcion

