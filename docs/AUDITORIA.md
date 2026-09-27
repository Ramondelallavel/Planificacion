# Auditoría de la aplicación (septiembre de 2026)

Revisión completa de la aplicación: backend, interfaz y edición navegador. Este documento recoge
qué se miró, qué se encontró y qué se cambió. Todos los arreglos llevan pruebas
(`backend/tests/test_auditoria.py`). La segunda pasada, centrada en la robustez, está al final.

## Cómo se ha hecho

| Paso | Herramienta | Resultado |
|---|---|---|
| Tipos | mypy (`--check-untyped-defs`) | 176 avisos. Casi todos son nombres reutilizados con otro tipo. Los posibles `None` se revisaron uno a uno y están protegidos por comprobaciones previas |
| Seguridad del código | bandit (severidad media o alta) | 0 hallazgos |
| Estilo y errores comunes | ruff (reglas `S`, `PERF`, `RUF`, `SIM`, `PLE`, `PLW`, `DTZ`) | nada relevante |
| Dependencias | `npm audit`, `pip-audit` | 0 vulnerabilidades conocidas |
| Cobertura | pytest-cov | 88 % antes y 90 % después: se añadieron pruebas en las zonas sin cubrir (incidencias, simulaciones, documentos, configuración, fichajes) |
| Permisos | listado de las 111 rutas de la API (115 tras la auditoría) con el permiso que exige cada una | todas piden sesión salvo el inicio de sesión; ver hallazgos S6 y S7 |
| Uso real | recorrido automático en Chromium de 18 pantallas × 5 roles × escritorio (1440 px) y móvil (390 px), más un detector de elementos que se salen de la pantalla | 0 errores de consola en todo el recorrido; hallazgos U1–U4 |

## Hallazgos y arreglos

Gravedad: **alta**, un riesgo real con los valores por defecto; **media**, fallos o riesgos con
consecuencias claras; **baja**, detalles.

### Seguridad

| # | Gravedad | Hallazgo | Arreglo |
|---|---|---|---|
| S1 | alta | Sin `HIDRAL_SECRETO`, las sesiones se firmaban con un valor conocido (`cambiar-en-produccion`): cualquiera podía fabricarse un acceso de administrador | Secreto aleatorio por instalación, guardado junto a los datos; nunca un valor fijo |
| S2 | media | Una sesión seguía valiendo tras dar de baja al usuario o cambiarle el rol, hasta caducar (12 h; 30 días en el navegador) | Cada petición comprueba el usuario y usa su rol actual |
| S3 | media | Sin límite de intentos de inicio de sesión | 5 fallos en 15 minutos bloquean esa cuenta durante ese tiempo; queda en la auditoría |
| S4 | media | No había forma de cambiar contraseñas ni de gestionar usuarios: las claves de ejemplo no se podían cambiar | Cambio de la propia clave (menú lateral) y pestaña «Usuarios y accesos» para el administrador; no se puede quitar el último administrador |
| S5 | media | Subidas sin límite de tamaño (PDF y CSV) | 300 MB por PDF y 10 MB por CSV, configurables; los ficheros vacíos se rechazan |
| S6 | baja | Las acciones de fichaje y la incidencia del operario solo exigían sesión, no el permiso correspondiente | Exigen «fichar» (o «fichar supervisado») e «incidencias» |
| S7 | baja | Cualquiera podía marcar como leído un aviso que no le correspondía | Solo el destinatario |
| S8 | baja | Sin cabeceras de seguridad HTTP | `nosniff`, `Referrer-Policy`, `X-Frame-Options`; `no-store` en la API |
| S9 | media (privacidad) | El texto de las páginas guardado para auditoría incluía teléfonos, correos y nombres de contacto (páginas 98–99 de la tanda real) | Las líneas con correo o teléfono se sustituyen por «[datos de contacto ocultos]» al importar. Las bases ya existentes se limpian una vez al arrancar. La interpretación del PDF no cambia (se hace antes). Se desactiva con `HIDRAL_OCULTAR_DATOS_PERSONALES=0` |

### Datos y motor

| # | Gravedad | Hallazgo | Arreglo |
|---|---|---|---|
| D1 | media | Un turno con horas imposibles (p. ej. 25:99) se guardaba y rompía el motor al planificar | Horas HH:MM, días 0–6 y pausas validados |
| D2 | media | Los parámetros de planificación admitían cualquier cosa (texto en un peso, horizonte negativo) | Validación por tipo y rango al guardar |
| D3 | media | Se podía registrar una avería sin máquina, una ausencia sin operario, etc. | Datos obligatorios según el tipo de incidencia; fin posterior al inicio |
| D4 | media | Cada replanificación guardaba un plan completo para siempre: la base (y en el navegador, su almacenamiento) crecía sin límite | Retención configurable: plan activo, definitivos, 15 oficiales archivados y 30 simulaciones |
| D5 | media | Sin migraciones: una columna nueva en una versión futura habría roto la base guardada en el navegador | Al arrancar se añaden las columnas que falten, con sus valores por defecto |
| D6 | baja | Ausencias con el fin antes del inicio, o para un operario inexistente | Rechazadas |
| D7 | baja | Al quitar una máquina, las operaciones fijadas a ella quedaban sin poder planificarse | Quedan libres para otra máquina de la sección y se avisa de cuántas |
| D8 | baja | En Carga de trabajo no contaban las personas cualificadas por tipo de operación, y un equipo sin nadie cualificado aparecía con capacidad | Corregido: sin personas cualificadas, capacidad cero, con el motivo |
| D9 | baja | El CSV de stock leía «1.234» como 1,234 | Números a la española y a la inglesa |
| D10 | baja | Los avisos de incidencias solo llegaban a los jefes de equipo, los registrados por un mando no avisaban a nadie y el riesgo rojo solo llegaba al planificador | Avisos a todos los mandos; cada rol ve lo suyo y lo de los mandos |

### Uso

| # | Gravedad | Hallazgo | Arreglo |
|---|---|---|---|
| U1 | alta (móvil) | En el móvil el menú ocupaba media pantalla en cada página | Menú plegable («☰ Menú») que se cierra al elegir pantalla |
| U2 | media | Las etiquetas de los indicadores salían cortadas (conflicto de estilos con las etiquetas pequeñas) | Corregido |
| U3 | media | En el móvil, paneles y tablas se salían de la pantalla | Rejillas que pasan a una columna y tablas con desplazamiento propio; 0 desbordes en las 17 pantallas |
| U4 | media | Pantalla del operario: el botón INICIAR aparecía verde aunque la operación estaba bloqueada, y el motivo se mostraba como un error | Motivo como aviso. El operario ve «INICIAR (necesita autorización)», desactivado; el jefe de equipo ve «INICIAR CON AUTORIZACIÓN» |
| U5 | baja | Botón «Entrar» sin tipo explícito | Corregido |

## Segunda pasada: robustez

Después de la auditoría se buscaron a propósito los fallos que no salen usando la aplicación con
normalidad: valores extremos, peticiones simultáneas, ficheros hostiles y los límites de la edición
navegador. Las pruebas están en `backend/tests/test_robustez.py` y `backend/tests/test_navegador.py`.

| Paso | Cómo | Resultado |
|---|---|---|
| Valores extremos en todas las rutas | Generador que lee la descripción OpenAPI de la API y manda a cada ruta, campo a campo: enteros enormes y negativos, NaN, infinito, ±10³⁰⁸, fechas imposibles o de los años 1 y 9999, textos de 5000 caracteres, caracteres nulos, inyección SQL y de HTML, rutas `../`, identificadores inexistentes, cuerpos vacíos o que no son un objeto y ficheros hostiles (vacíos, basura, nombres con `../`, CSV con NaN) | 220 errores internos (500) al empezar; **0 en 1828 peticiones** al terminar, en SQLite y en PostgreSQL 16 |
| Acceso sin sesión | Todas las rutas (salvo el inicio de sesión y la de salud) sin token y con un token falso | todas responden 401 o 422; ninguna da datos |
| Peticiones simultáneas | Dos sesiones de base de datos que hacen lo mismo a la vez | la base de datos impide el resultado imposible; ver R3 |
| PDF hostiles | Cifrado, de 0 bytes, cortado a la mitad, que no es PDF, solo páginas en blanco, con demasiadas páginas | todos acaban en un estado claro (ERROR con el motivo, o sin datos) y la aplicación sigue funcionando |
| Edición navegador | Chromium: dos pestañas a la vez, copias no válidas (no JSON, otro JSON, comprimido roto, base cortada, cabecera falsa), una copia buena, 6 recargas seguidas | ver R7–R10; 0 errores de consola |

| # | Gravedad | Hallazgo | Arreglo |
|---|---|---|---|
| R1 | alta | La base de datos se grababa **después** de enviar la respuesta: si la grabación fallaba (por ejemplo, por un dato duplicado), la pantalla ya había dicho «guardado» | Se graba antes de responder; un fallo al grabar llega como error |
| R2 | media | Valores extremos rompían rutas con un error interno: enteros enormes, fechas fuera de rango, NaN o infinito en cantidades, caracteres nulos, códigos de sección o turno inexistentes, un CSV con un separador desconocido, la página de un PDF borrado del almacén | Validación común de todas las entradas (enteros de 32 bits, números finitos hasta 10⁹, textos de hasta 4000 caracteres sin caracteres nulos, listas de hasta 5000 elementos) y límites en los parámetros de consulta. Mensajes claros (400, 404, 409) que dicen qué falta, por ejemplo «No existe la sección X. Créala antes en Configuración → Secciones», y nueva opción para crear secciones. Cualquier error imprevisto responde un mensaje en JSON y queda en el registro |
| R3 | media | Dos peticiones a la vez podían dejar a un operario con dos trabajos abiertos, o dos planes oficiales activos | Índices únicos en la base de datos: la segunda petición recibe un 409 que lo explica («Otra persona está generando el plan…») |
| R4 | media | No había límite de páginas: un PDF enorme ocupaba el procesamiento (y en el navegador, la memoria) sin control | Límite de páginas (5000, `HIDRAL_MAX_PAGINAS`); el documento queda en ERROR con el motivo |
| R5 | baja | El inicio de sesión respondía antes cuando el usuario no existía: se podía averiguar qué usuarios existen | Mismo cálculo exista o no el usuario |
| R6 | media | La edición con servidor leía peticiones de cualquier tamaño antes de comprobarlas | Se cortan con un 413 antes de leerlas (también si llegan por trozos, sin tamaño declarado) |
| R7 | media | Edición navegador: dos pestañas abiertas guardaban sobre los mismos datos y los cambios de una pisaban los de la otra | Solo una pestaña usa los datos. La segunda lo explica y ofrece «Usar aquí»; la primera deja de guardar al momento, lo avisa y permite descargar una copia de lo que tenía |
| R8 | media | Edición navegador: restaurar un fichero equivocado o dañado sustituía los datos y podía dejar la aplicación sin poder entrar | Antes de tocar nada se comprueban el formato, el tamaño, la integridad de la base, que sea de HIDRAL y que tenga algún usuario activo. Si aun así no abre, se vuelve a los datos anteriores |
| R9 | media | Edición navegador: si el navegador no podía guardar (almacenamiento lleno), el aviso no se mostraba en ningún sitio | Aviso visible en todas las pantallas, con qué hacer; además se pide al navegador que no borre los datos por falta de espacio |
| R10 | baja | Edición navegador: los errores del motor llegaban a la pantalla con toda la traza de Python | Solo el mensaje; la traza, en la consola |
| R11 | baja | Al exportar a CSV, un texto que empieza por `=`, `+`, `-` o `@` (de un PDF o tecleado por cualquiera) Excel lo ejecutaba como fórmula | Se exporta con un apóstrofo delante: Excel lo muestra como texto |
| R12 | baja | Si una pantalla fallaba al dibujarse, la aplicación entera se quedaba en blanco | Cada pantalla tiene su barrera: aviso con «Reintentar» y el resto sigue funcionando |
| R13 | baja | Errores poco claros en la interfaz: «Failed to fetch» sin conexión, «Error 422» con datos no válidos | «No hay conexión con el servidor…», el campo y el motivo de lo rechazado, y textos para 413, 429 y 502–504 |
| R14 | baja | Las bases ya existentes no recibían los índices nuevos (solo las columnas) | Al arrancar se crean también los índices que falten |

## Lo que queda (recomendaciones, sin implementar)

- **Migraciones formales** (Alembic) si alguna vez hay que renombrar columnas o cambiarles el tipo.
  Hoy solo se añaden columnas.
- **Inicio de sesión corporativo** (Microsoft Entra ID o LDAP) y doble factor para la instalación con
  servidor.
- **HTTPS y límite de peticiones por minuto** en el proxy que publique la aplicación (nginx,
  Traefik…). La aplicación ya limita el tamaño de cada petición y los intentos de inicio de sesión.
- **Edición navegador**: sigue siendo de una sola persona y una sola pestaña por navegador. Para un
  equipo, la edición con servidor.
- Los avisos de mypy son ruido, pero tiparlos del todo evitaría que un fallo real se esconda entre
  ellos.
