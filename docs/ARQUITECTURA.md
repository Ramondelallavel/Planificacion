# Arquitectura

## Vista general

```
                 ┌──────────────────────── Interfaz web (React) ────────────────────────┐
                 │ Control Tower · Gantt · Plan por turno · Incidencias · Simulación     │
                 │ Tandas/Aparatos/OF · Importación · Configuración · Auditoría · Operario│
                 └───────────────────────────────┬──────────────────────────────────────┘
                                                 │ REST /api (token firmado, permisos por rol)
┌────────────────────────────────────────────────▼─────────────────────────────────────────────┐
│ API (FastAPI)                                                                                 │
│  documentos · estructura · plan · planta · recursos · dashboard · gestión · auth               │
├───────────────┬──────────────────────────┬───────────────────────────┬───────────────────────┤
│ Ingesta       │ Planificación (memoria)  │ Servicios                 │ Integraciones         │
│ PDF por       │ prioridad · programador  │ operaciones y tiempos     │ sistema maestro       │
│ bloques       │ riesgo · cuellos · KPIs  │ fichajes · aprendizaje    │ ORTEMS · MRP ·        │
│ (cola)        │ replanificación · what-if│ auditoría                 │ Teamcenter (CSV)      │
└──────┬────────┴────────────┬─────────────┴──────────────┬────────────┴──────────┬────────────┘
       │                     │                            │                       │
┌──────▼──────┐     ┌────────▼────────────────────────────▼───────────────────────▼──────────┐
│ Almacén de  │     │ Base de datos (PostgreSQL en producción, SQLite en desarrollo/pruebas)  │
│ ficheros    │     │ documentos · estructura de fabricación · recursos · planes · ejecución │
│ (SHA-256)   │     │ incidencias de datos · orígenes · auditoría · parámetros versionados    │
└─────────────┘     └────────────────────────────────────────────────────────────────────────┘
       ▲
┌──────┴──────────────────┐
│ Trabajador(es) de cola  │  python -m hidral_plan.ingesta.cola  (FOR UPDATE SKIP LOCKED)
└─────────────────────────┘
```

Un solo paquete Python (`hidral_plan`) y una sola imagen: la API y los trabajadores son el mismo
código con distinto comando. El motor de planificación trabaja sobre una **instantánea en memoria**
(`planificacion/modelo.py`) cargada de la base de datos; así la simulación y la replanificación
operan sobre copias sin tocar el plan oficial, y el resultado se persiste solo cuando procede.

## 1. Ingesta documental (`ingesta/`)

```
subida → SHA-256 en streaming → ¿duplicado exacto? → ¿nueva versión (mismo nombre, otro hash)?
       → almacén + Documento + TrabajoProcesamiento (EN_COLA)  ← la API responde 202 al instante
trabajador: tamaño de bloque adaptativo → por bloque:
       extraer spans (PyMuPDF; OCR solo si la página no tiene texto) → clasificar página
       → parser del tipo de hoja con ContextoDocumento ligero → persistir bloque + checkpoint
       → liberar memoria (store_shrink) → latido / % / ETA / contadores
post-proceso: enlazar aparatos · grafo de dependencias · ciclos (Tarjan) · semanas
       · operaciones y tiempos · validación · informe "DOCUMENTO PROCESADO"
```

- **Nunca se carga el PDF entero**: se abre el fichero y se procesan las páginas del bloque; entre
  bloques solo viaja el `ContextoDocumento` (cabecera de la OF en curso, sección, aparato, OF ya
  vistas), que se serializa en el checkpoint. El caso D de las pruebas procesa 600 páginas con un
  pico de memoria Python medido por debajo de 200 MB.
- **Tamaño de bloque adaptativo** (`bloques.py`): se estima con páginas, tamaño de fichero y una
  muestra (texto e imágenes por página) contra `HIDRAL_BLOQUE_MEMORIA_MB`, y se corrige con el
  tiempo real por página.
- **Reanudable**: cada bloque y su contexto se guardan en la misma transacción. Un trabajo cuyo
  latido caduca (el proceso murió) lo retoma otro trabajador desde el último bloque.
- **Duplicados y versiones**: mismo hash → `DUPLICADO` (no se reprocesa). Mismo nombre y otro hash
  → nueva versión; la anterior queda `SUSTITUIDO` y se conserva.
- **Trazabilidad**: cada dato extraído guarda documento, página y texto de origen; la interfaz
  muestra la imagen de la página junto al dato.

El detalle de cada tipo de hoja está en [FORMATO_PDF_TANDA.md](FORMATO_PDF_TANDA.md).

## 2. Operaciones y tiempos (`servicios/operaciones.py`)

Cada OF se convierte en operaciones planificables:

- **Tipo de operación**: reglas por palabra clave sobre el Grupo HF o el título del programa
  (`mapeo_operaciones`, configurable) y regla por flujo de sección (LCH → `CORTE_LASER`).
- **Máquina**: si el programa cita una máquina (LASERTUB, FICEP, GEKA, SABI…) se busca el recurso
  por alias; si no existe → incidencia `OPERACION_SIN_RECURSO`.
- **Programación CNC**: si la sección requiere programación y el tipo está en `tipos_con_programa`,
  se crea una operación `PROGRAMACION` previa y la OF queda `PENDIENTE_PROGRAMACION`; lo que
  depende de ella se planifica como **provisional**.
- **Duración**: `preparación + min/unidad × cantidad + min/línea × líneas` con el tiempo estándar
  más específico (artículo > grupo HF > tipo de operación > sección). Sin tiempo estándar →
  incidencia `SIN_TIEMPO_ESTANDAR` y la operación no se planifica. La explicación del cálculo se
  guarda en `origen_duracion`.

## 3. Planificación (`planificacion/`)

### Índice de prioridad (`prioridad.py`)
Factores normalizados 0..1 y ponderados con `pesos_prioridad`: holgura frente a la semana,
cercanía de la semana, fuera de plazo, OF que esperan por esta, aparato casi completo, alimenta un
cuello de botella, prioridad ORTEMS y marca de urgente. Se devuelve el valor, la contribución de
cada factor y los motivos en lenguaje de planta.

### Programador (`programador.py`)
Generación en serie (serial SGS) guiada por la prioridad, con *backfilling*: cada operación va al
primer hueco factible y se elige la combinación recurso/operario que termina antes.

| Restricciones duras (nunca se violan) | Restricciones blandas (desempate configurable) |
|---|---|
| recurso capaz (sección, tipo de operación, máquina citada) | agrupar familia de setup en la misma máquina |
| operario cualificado, en su turno y sin ausencia | equilibrar carga de recursos y operarios |
| precedencias dentro de la OF y entre OF | |
| recurso sin avería/parada y sin solape | |
| material disponible (o fecha prevista) | |
| programación CNC antes que la máquina | |

Los calendarios (`calendario.py`) salen de los turnos con sus pausas, días laborables y festivos;
una operación puede repartirse en tramos que saltan pausas y cambios de turno. Lo que no se puede
planificar no se fuerza: queda en la lista de **no planificables** con su motivo
(`SIN_RECURSO`, `SIN_OPERARIO`, `SIN_DURACION`, `ESPERANDO_MATERIAL`, `PREDECESORA_NO_PLANIFICABLE`,
`PREDECESORA_EXTERNA`, `SIN_HUECO` en el horizonte…).

Antes de generar un plan se ejecutan 7 comprobaciones previas: validar datos, recursos,
trabajadores, dependencias, materiales, programación y conflictos. Un plan **definitivo** no se genera con incidencias
críticas abiertas (`PlanBloqueado`); un plan **provisional** sí, marcado como tal.

### Riesgo (`riesgo.py`)
Sobre el plan resultante, por OF, aparato, tanda y recurso. La holgura se mide en **horas
laborables** entre el fin previsto (más la cadena que falta detrás) y el límite de la semana
de fabricación (`semana_fabricacion`: por defecto viernes 23:59).

| Nivel | Condición (umbrales configurables en `umbrales_riesgo`) |
|---|---|
| ROJO | no planificable, o holgura negativa (no llega a la semana) |
| NARANJA | holgura < 8 h laborables |
| AMARILLO | holgura < 24 h, semana desconocida, o pendiente de programación |
| VERDE | resto |

Cada nivel va con sus motivos y acciones sugeridas; el Control Tower añade "¿qué pasa si no actúo?".

### Cuellos de botella y KPIs (`analisis.py`)
Pre-análisis de carga por recurso frente a capacidad antes de programar y post-análisis sobre el
plan. KPIs de calidad del plan: cumplimiento de semana por aparato, retraso total, cambios de setup,
horas muertas, WIP medio, utilización y carga por recurso.

### Replanificación incremental (`replanificacion.py`)
Ante un evento (avería, ausencia, falta de material, retraso, cambio de prioridad, OF urgente):

1. se aplica el evento a la instantánea;
2. se calcula la **zona afectada** (solo las operaciones que el evento invalida);
3. lo demás se congela, igual que lo que está en curso o empieza dentro de `congelar_minutos`;
4. se recolocan las afectadas; si empujan a una sucesora congelada, esta entra en la zona (propagación mínima);
5. se devuelve ANTES / DESPUÉS / MOTIVO / IMPACTO de cada operación que cambia y el riesgo de cada
   tanda antes y después.

La **OF urgente** se simula por inserción con desplazamiento: el resultado explica qué OF se retrasan
y cuánto, y un responsable lo acepta o rechaza. Rechazar deja el plan como estaba; en ambos casos
la decisión queda auditada.

### Simulación what-if (`simulacion.py`)
Escenarios combinables (averías, ausencias, falta de operarios por sección, adelantar OF, falta de
material, retrasos, recursos extra, otros pesos de prioridad) sobre una copia. Nunca escribe en el
plan oficial; puede guardarse como plan `SIMULACION` para compararlo.

### Cambios manuales (`servicio.py`)
Mover o reasignar una operación pasa por `restricciones.validar_asignacion`: si viola una
restricción dura se rechaza con los motivos (y el intento queda auditado); si es válido se aplica,
se propagan las sucesoras y puede **bloquearse** para que las replanificaciones no la muevan.

## 4. Ejecución en planta (`servicios/ejecucion.py`)

- **Fichajes**: INICIAR / PAUSAR / REANUDAR / TERMINAR (total o parcial). Iniciar comprueba bloqueos
  **duros** (operación terminada, pendiente de programación, operario no cualificado, máquina
  averiada/parada) y **blandos** (predecesora sin terminar, antes de hora…); los blandos solo los
  puede saltar un supervisor, jefe de equipo o planificador, y queda registrado quién autorizó.
- **Planificado frente a real**: cada fichaje guarda duración planificada y real; la desviación
  alimenta el aprendizaje.
- **Aprendizaje de tiempos**: compara real/planificado por tiempo estándar (una muestra por
  operación). Con muestras y desviación suficientes **propone** un ajuste explicado; aplicarlo
  requiere aprobación, crea una versión nueva del tiempo estándar y es reversible.
- **Avisos**: incidencias del operario notifican al jefe de equipo; las replanificaciones que
  cambian el trabajo de un operario le generan un aviso en su pantalla.

## 5. Integraciones (`integraciones/`)

Cada tipo de dato tiene un **sistema maestro** y un respaldo (matriz `SISTEMA_MAESTRO`, visible en
Configuración → Integraciones). Ejemplos: prioridad y semana → ORTEMS; material y rutas → MRP;
información técnica → Teamcenter; contenido de hoja (piezas, destinos, bultos) → PDF. Cada valor
importado deja su `Origen` (sistema, fila); si dos fuentes discrepan manda el maestro y la
discrepancia queda como incidencia de datos con ambos valores.

Los adaptadores actuales leen exportaciones CSV (`AdaptadorCSV`, con mapeo de columnas opcional).

## 6. Seguridad y auditoría

- Contraseñas con PBKDF2-SHA256; sesión con token firmado HMAC (`HIDRAL_SECRETO`) y caducidad.
- Roles y permisos (`seguridad.py`):

| Rol | Permisos |
|---|---|
| ADMINISTRADOR | todo |
| PLANIFICADOR | ver, importar, planificar, modificar plan, configurar, recursos, incidencias, simular, validar datos, aprobar estimaciones, fichar supervisado |
| JEFE_EQUIPO | ver, importar, planificar, modificar plan, incidencias, simular, validar datos, fichar supervisado |
| SUPERVISOR | ver, incidencias, simular, validar datos, fichar supervisado |
| OPERARIO | su propio trabajo, fichar, incidencias |
| CONSULTA | ver |

- **Auditoría**: toda escritura relevante (importaciones, planes, movimientos, rechazos, fichajes,
  configuración, aprendizaje) registra usuario, fecha, acción, entidad, antes, después, motivo y si
  fue automática.
- **Parámetros versionados**: cada cambio de `ParametroConfig` incrementa su versión y se audita.

## 7. Decisiones de diseño

| Decisión | Motivo |
|---|---|
| Procesamiento determinista, sin IA | Los datos de fabricación no admiten suposiciones; toda regla es trazable y reproducible |
| Cola en base de datos (no broker externo) | Un componente menos que operar; `SKIP LOCKED` permite varios trabajadores |
| Motor en memoria sobre instantánea | Simulaciones y replanificación sobre copias baratas; el plan oficial solo cambia al persistir |
| SGS con backfilling en lugar de solver MIP | Tiempos de respuesta de segundos con cientos de OF, resultado explicable paso a paso |
| Hora local naive | Todo el dominio (turnos, semanas) es de planta; la zona horaria se fija en el despliegue |
