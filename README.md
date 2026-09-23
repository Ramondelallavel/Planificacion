# HIDRAL · Planificación, programación y control de fabricación

Sistema APS/MES para HIDRAL. Convierte las tandas en PDF (hojas de fabricación, órdenes de
fabricación, listas de materiales y relaciones de bultos), junto con los datos de ORTEMS, MRP y
Teamcenter y el estado real de planta, en:

**planificación → asignación de OF → recursos y operarios → plan por turno → secuencia → control en
tiempo real → riesgos → replanificación incremental → trazabilidad → avisos al operario → análisis.**

Principios que el código respeta en todo momento:

- **No se inventan datos.** Lo que no está en el documento o en la configuración aparece como
  `DATO NO DISPONIBLE` o genera una incidencia de datos `REVISIÓN NECESARIA` con página y texto de origen.
- **Todo es determinista y explicable.** Cada asignación guarda por qué se eligió ese recurso,
  operario y hueco; cada cambio del plan guarda ANTES / DESPUÉS / MOTIVO / IMPACTO / RIESGO.
- **La persona decide.** Los cambios manuales pasan por el motor de restricciones, exigen motivo y
  quedan auditados; las simulaciones nunca tocan el plan oficial sin aceptación explícita.
- **Una tanda no tiene un número fijo de aparatos.** La estructura
  TANDA → APARATO/PEDIDO → BULTO → COMPONENTES → OF → OPERACIONES → RECURSOS sale del documento.

## Contenido

| Carpeta | Qué hay |
|---|---|
| `backend/hidral_plan/ingesta` | Pipeline de PDF por bloques (streaming, reanudable, OCR solo si hace falta), parsers por tipo de hoja, grafo de dependencias, validación |
| `backend/hidral_plan/planificacion` | Índice de prioridad, programador con restricciones (capacidad finita), riesgo, cuellos de botella, KPIs, replanificación incremental, OF urgente, what-if |
| `backend/hidral_plan/servicios` | Derivación de operaciones y tiempos, fichajes, aprendizaje de tiempos (propone, nunca aplica solo), auditoría |
| `backend/hidral_plan/integraciones` | Matriz de sistema maestro y adaptadores ORTEMS / MRP / Teamcenter (CSV) |
| `backend/hidral_plan/api` | API REST (FastAPI) con roles y permisos; sirve también la interfaz web |
| `backend/config/fabrica_ejemplo.yaml` | Configuración de fábrica **de ejemplo** (ver aviso abajo) |
| `backend/tests` | Casos obligatorios A–P, PDF real, unitarios y API |
| `frontend` | Interfaz web (React + TypeScript): Control Tower, Gantt, operario, simulación… |
| `docs` | [Arquitectura](docs/ARQUITECTURA.md) · [Formato del PDF de tanda](docs/FORMATO_PDF_TANDA.md) · [Modelo de datos](docs/MODELO_DATOS.md) · [Casos de prueba](docs/CASOS_PRUEBA.md) |

## Qué se puede hacer

| Pantalla | Para qué |
|---|---|
| **Control Tower** | Qué pasa ahora: tandas y aparatos en riesgo con sus motivos, qué hacer en las próximas 2 h, OF retrasadas, máquinas paradas, personal y acciones recomendadas |
| **Indicadores** | KPIs del plan (cumplimiento de semana, retraso, setups, utilización, WIP) e histórico |
| **Plan · Gantt** | Por máquina, por tanda/OF o por operario; zoom hora/turno/día/semana; turnos y jornadas extra sombreados, límites de semana de fabricación; filtros por tanda, aparato, riesgo y texto; resaltar la cadena de dependencias de una OF; arrastrar para mover (validado por el motor de restricciones); exportar a CSV |
| **Plan por turno** | Lo que toca a cada máquina y operario turno a turno |
| **Capacidad** | Mapa de calor ocupación/capacidad por máquina y día (turnos, festivos, jornadas extra, paradas) y las máquinas más cargadas; clic en una celda para ver qué hay planificado |
| **Carga de trabajo** | Horas pendientes de cada equipo (sección) frente a la capacidad de sus máquinas y su gente; rendimiento del equipo en % sobre los tiempos estándar; mover carga entre máquinas o equipos (con vista previa); añadir gente o máquinas; nueva OF a mano |
| **Materiales** | Lo que consumen las OF abiertas (consumos y componentes de compra de los PDF) frente a stock y entradas previstas; importar stock en CSV; «Aplicar al plan» bloquea las OF sin material o las retrasa hasta la entrada que las cubre |
| **Seguimiento** | Plan frente a real: adherencia, trabajos en curso y si exceden su tiempo, pendientes que ya debían estar, desviación real/previsto por sección y operación (CSV) |
| **Incidencias** | Averías, faltas de material, calidad…; replanifican solo la zona afectada |
| **Simulación** | «¿Qué pasa si…?» (averías, falta de personal, turnos extra, máquinas extra, adelantar OF) sobre una copia; «Aplicar y replanificar» hace reales las decisiones (turnos extra, urgencias, pesos); OF urgente con aceptación; **comparador** de simulaciones guardadas frente al plan actual |
| **Asistente (Claude)** | Solo en la edición publicada en claude.ai: preguntas en lenguaje natural que Claude responde consultando los datos de la aplicación y simulando sobre copias; nunca cambia el plan |
| **Tandas, aparatos y OF** | Añadir tandas arrastrando uno o varios PDF (y replanificar con ellas); editar producto y semana de fabricación de tanda o aparato; sacar del plan, archivar o eliminar una tanda (con su PDF, que se puede volver a importar); priorizar todas las OF de una tanda o aparato; editar, añadir o quitar operaciones de una OF; crear y eliminar OF a mano |
| **Importar documentos** | Carga de tandas en PDF procesadas por bloques, con progreso e incidencias de datos |
| **Pantalla de operario** | Mi trabajo, iniciar/pausar/terminar, avisos de cambios de plan, incidencias |
| **Configuración** | Máquinas (duplicar, dar de baja), secciones, operarios (alta de varios a la vez, baja) y cualificaciones, turnos, **calendario** (festivos y jornadas extra por sección), tiempos estándar y aprendizaje, pesos de prioridad |
| **Auditoría** | Quién cambió qué, cuándo, antes/después y por qué |

En toda la aplicación: búsqueda global (Ctrl+K) de OF, tandas, aparatos, artículos, máquinas y
operarios, y centro de **avisos** para los mandos (incidencias de planta, aparatos que pasan a
riesgo rojo).

## Aviso: datos de fábrica de ejemplo

El PDF de tanda no contiene máquinas, turnos, operarios ni tiempos de operación. Para poder
planificar, `backend/config/fabrica_ejemplo.yaml` trae una configuración **ficticia** (recursos
basados en los nombres de máquina que aparecen en el PDF, operarios OP01–OP21 inventados, tiempos
estándar orientativos). Todo lo que se carga desde ese fichero queda marcado `EJEMPLO` en la
interfaz. Antes de usar el plan en planta hay que sustituirlo por los datos reales de HIDRAL
(desde **Configuración de fábrica** o con un YAML propio: `python -m hidral_plan.semilla mi_fabrica.yaml`).

La sección `PLPINO` se deja sin configurar a propósito para que se vea cómo trata el sistema una
sección sin recursos: sus OF quedan "no planificables" con el motivo explicado.

## Arranque rápido con Docker

```bash
cp .env.example .env            # rellenar HIDRAL_DB_CLAVE y HIDRAL_SECRETO
docker compose up -d --build    # PostgreSQL + API/interfaz + trabajador de documentos
# solo para una demostración: configuración de fábrica de ejemplo y usuarios demo
docker compose exec api python -m hidral_plan.semilla config/fabrica_ejemplo.yaml
```

Abrir <http://localhost:8000> (API documentada en `/docs`). Usuarios demo creados por la semilla,
todos con clave `hidral` (o la de `HIDRAL_CLAVE_DEMO` si se define): `admin`, `planificador`,
`jefe`, `supervisor`, `consulta`, `op01`, `op13`, `op17`. **Cámbielas o elimínelas en producción.**

Detrás de un proxy con inspección TLS, la imagen admite el certificado como secreto de build:
`docker build --build-arg HTTPS_PROXY=… --secret id=ca,src=ca-proxy.crt -t hidral-plan .`
Con `--build-arg INSTALAR_OCR=0` se omite tesseract (imagen más ligera; las páginas escaneadas
quedarán como `SIN_TEXTO` con su incidencia).

## Edición navegador (sin servidor)

La misma aplicación puede ejecutarse entera dentro del navegador: el backend Python funciona
sobre [Pyodide](https://pyodide.org) (Python compilado a WebAssembly) en un Web Worker, con su
base SQLite guardada en el almacenamiento del navegador (IndexedDB). El código de negocio es
exactamente el del servidor; `backend/hidral_plan/navegador.py` solo adapta el entorno (sin
hilos, procesamiento de PDF bloque a bloque, copia y restauración de la base).

```bash
python herramientas/empaquetar_navegador.py        # genera frontend/dist-navegador (≈44 MB)
cd frontend/dist-navegador && python -m http.server # y abrir http://localhost:8000
```

Es la edición que se publica como página en claude.ai: allí añade «Pedir un cambio» (envía a
Claude un comentario sobre la pantalla actual), el **Asistente** (preguntas a Claude sobre los
datos, con la cuenta de quien pregunta), copias automáticas en la nube de la página y descargas. Es monousuario por navegador: para un equipo que comparte datos, la edición con
servidor (Docker) es la adecuada. Limitaciones: sin OCR (tesseract no existe en WebAssembly) y
pydantic en versión 2.14 beta, la primera con rueda WebAssembly publicada.

## Desarrollo local

Requisitos: Python ≥ 3.11 y Node ≥ 20.

```bash
# backend
cd backend
pip install -e ".[dev]"                       # añadir ,postgres u ,ocr si se necesitan
python -m hidral_plan.semilla config/fabrica_ejemplo.yaml
uvicorn hidral_plan.api.app:app --reload      # http://127.0.0.1:8000 (SQLite en backend/datos/)

# interfaz (otra terminal)
cd frontend
npm install
npm run dev                                    # http://localhost:5173, redirige /api al backend
```

En desarrollo el trabajador de documentos corre en un hilo de la propia API
(`HIDRAL_WORKER_EN_PROCESO=1`). En producción se lanza aparte, uno o varios:
`python -m hidral_plan.ingesta.cola`.

### Variables de entorno

| Variable | Por defecto | Uso |
|---|---|---|
| `HIDRAL_DB_URL` | SQLite en `backend/datos/hidral.db` | `postgresql+psycopg://usuario:clave@host/bd` en producción |
| `HIDRAL_ALMACEN_DIR` | `backend/datos/almacen` | PDF originales (por SHA-256); compartido entre API y trabajadores |
| `HIDRAL_SECRETO` | `cambiar-en-produccion` | Firma de sesiones. **Obligatorio cambiarlo** |
| `HIDRAL_TOKEN_HORAS` | `12` | Duración de la sesión |
| `HIDRAL_BLOQUE_MIN` / `_MAX` / `_MEMORIA_MB` | `5` / `50` / `64` | Límites del tamaño adaptativo de bloque |
| `HIDRAL_OCR` | `auto` | `auto`: OCR solo en páginas sin texto · `off`: nunca |
| `HIDRAL_WORKER_EN_PROCESO` | `1` | `0` si los trabajadores corren como procesos aparte |
| `HIDRAL_AHORA` | — | Reloj fijo ISO 8601 para demostraciones y pruebas |
| `HIDRAL_FRONTEND_DIR` | `frontend/dist` | Interfaz compilada que sirve la API |
| `HIDRAL_CORS` | `http://localhost:5173,…` | Orígenes permitidos en desarrollo |

Las fechas del sistema son **hora local de planta**: el contenedor debe tener la zona horaria de la
fábrica (`TZ=Europe/Madrid` en `docker-compose.yml`).

## Pruebas

```bash
cd backend
python -m pytest                     # SQLite temporal
HIDRAL_TEST_DB_URL=postgresql+psycopg://usuario@host/bd_pruebas python -m pytest   # ¡vacía esa base!
ruff check .
cd ../frontend && npm run build && npm run lint
```

Los tests con el PDF real (`tests/test_pdf_real.py`) se omiten si el fichero no está en
`backend/tests/fixtures/` (no se versiona porque contiene datos de cliente); ver
[docs/CASOS_PRUEBA.md](docs/CASOS_PRUEBA.md).

## Límites conocidos de esta versión

- **Formatos de hoja**: los parsers se han construido y validado con la tanda de ejemplo 2210
  (hojas por Grupo HF, CAB de puertas, LCH, lista de materiales y relación de bultos). Una página con
  otro formato no se interpreta: queda como `PAGINA_NO_CLASIFICADA` con su texto para revisión.
- **Integraciones**: ORTEMS, MRP y Teamcenter se importan desde exportaciones CSV. Un conector
  directo (API o base de datos) se añade implementando la misma interfaz de adaptador.
- **Sin inteligencia artificial en el motor**: ingesta, planificación, riesgo y replanificación son
  deterministas. La edición con servidor no envía datos a servicios externos. La edición publicada
  en claude.ai guarda copias de la base en la nube de la página (privada), envía a Claude los
  comentarios de «Pedir un cambio» y, solo cuando alguien usa el Asistente, los datos que Claude
  consulta para responder (resúmenes del plan, OF, capacidad, seguimiento). El Asistente no
  escribe en el plan: como mucho guarda simulaciones, que no lo modifican.
- **Esquema de base de datos**: se crea al arrancar (`create_all`). No hay migraciones
  versionadas (Alembic); un cambio de esquema en una instalación con datos requiere migración manual.
