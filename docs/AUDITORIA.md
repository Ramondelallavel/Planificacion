# Auditoría de la aplicación (septiembre de 2026)

Revisión completa de la aplicación: backend, interfaz y edición navegador. Este documento recoge
qué se miró, qué se encontró y qué se cambió. Todos los arreglos llevan pruebas
(`backend/tests/test_auditoria.py`).

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

## Lo que queda (recomendaciones, sin implementar)

- **Migraciones formales** (Alembic) si alguna vez hay que renombrar columnas o cambiarles el tipo.
  Hoy solo se añaden columnas.
- **Inicio de sesión corporativo** (Microsoft Entra ID o LDAP) y doble factor para la instalación con
  servidor.
- **HTTPS y límite de peticiones** en el proxy que publique la aplicación (nginx, Traefik…).
- **Edición navegador**: sigue siendo de una sola persona por navegador. Para un equipo, la edición
  con servidor.
- Los avisos de mypy son ruido, pero tiparlos del todo evitaría que un fallo real se esconda entre
  ellos.
