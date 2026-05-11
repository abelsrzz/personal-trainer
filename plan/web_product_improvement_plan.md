# Web Product Improvement Plan

## Objetivo

Convertir la web de RunPilot y su sistema agentico de soporte en una superficie operativa completa: observar, decidir, actuar y conversar con el sistema desde un unico sitio.

## Estado actual resumido

La web ya ofrece una base solida:

- resumen operativo y plan de hoy
- planificados en semana, lista y calendario
- dashboard con decision automatica
- detalle diario de plan, ejecucion, revisiones y carreras
- feedback post-entreno
- vistas de atleta, ciclo, carreras y plan general

La principal limitacion actual es que la capa de accion todavia es estrecha: hay pocas acciones ejecutables y casi ningun bucle cerrado de replanificacion.

## Principios de producto

1. Cada lectura importante debe poder convertirse en una accion clara.
2. Cada accion debe dejar rastro operativo y ser reversible cuando tenga sentido.
3. La web debe reutilizar el motor actual antes de crear logica paralela.
4. La UX debe favorecer decisiones rapidas en movil y escritorio.

## Roadmap por fases

### Fase 1. Cerrar el bucle diario

Objetivo: que el atleta pueda reportar su estado, recibir ajuste y ejecutar el dia desde la web.

Incluye:

- Punto 1. Replanificacion real desde la web
- Punto 2. Check-in diario rapido
- Punto 6. Semana operativa mas accionable
- Punto 9. `/chat` web con OpenCode remoto

### Fase 2. Hacer visible el control del proceso

Objetivo: que la web explique mejor si el plan se esta cumpliendo y por que.

Incluye:

- Punto 3. Comparativa plan vs realidad
- Punto 4. Centro de decisiones del coach
- Punto 5. Seguimiento de molestias y riesgo

### Fase 3. Subir el nivel de inteligencia deportiva

Objetivo: transformar la web en una herramienta clara de progreso y preparacion competitiva.

Incluye:

- Punto 7. Insights de progreso reales
- Punto 8. Preparacion de carrera
- Punto 10. Nutricion, hidratacion y suplementacion

## Iniciativas

### 1. Replanificacion real desde la web

Problema:
Hoy la web permite marcar estados operativos como `done`, `skipped` o `alternative_requested`, pero no recompone automaticamente el dia ni la semana.

Resultado esperado:
El usuario debe poder pedir un ajuste y recibir una alternativa accionable sin salir de la web.

Capacidades:

- generar alternativa para la sesion de hoy
- mover una sesion a otro dia viable
- reducir carga manteniendo el objetivo semanal
- recomponer la semana tras una sesion perdida
- registrar la decision y el motivo

Cambios probables:

- nueva logica de replanificacion en backend reutilizando `coach_decision`, `semana_actual` y libreria de sesiones
- acciones nuevas en detalle de planificado, vista diaria e inicio
- historial de cambios operativos por sesion y por semana

Criterios de aceptacion:

- una solicitud de alternativa produce una propuesta concreta
- la propuesta deja trazabilidad
- el usuario puede aceptar, descartar o pedir otra opcion

### 2. Check-in diario rapido

Problema:
Falta la senal previa al entreno. El sistema decide con historico, pero no con el estado subjetivo del dia.

Resultado esperado:
Antes del entreno, el atleta puede informar como llega en menos de 20 segundos.

Capacidades:

- energia
- sueno
- dolor o molestia
- ganas de entrenar
- tiempo disponible real
- nota opcional

Cambios probables:

- nuevo estado diario persistido por fecha
- bloque visible en inicio y en `/calendar/day/{day}`
- influencia explicita en el plan de hoy y en las recomendaciones

Criterios de aceptacion:

- el formulario funciona bien en movil
- el check-in modifica la lectura operativa del dia cuando aplica
- queda claro por que el sistema cambia o mantiene la sesion

### 3. Comparativa plan vs realidad

Problema:
La web muestra plan y ejecucion, pero no ofrece una lectura agregada del desvio.

Resultado esperado:
El usuario debe poder entender si esta cumpliendo el plan semanal y por bloque.

Capacidades:

- km planificados vs realizados
- calidad planificada vs completada
- sesiones movidas, saltadas y sustituidas
- adherencia semanal y por bloque
- vista de desvio por tipo de sesion

Cambios probables:

- nueva agregacion de metricas sobre planificados y completados
- pantalla dedicada o modulo fuerte en dashboard/cycle
- filtros por semana, bloque y rango de fechas

Criterios de aceptacion:

- el usuario entiende en segundos si va por delante, alineado o por detras
- las desviaciones criticas se ven sin abrir cada entrenamiento

### 4. Centro de decisiones del coach

Problema:
El dashboard explica la decision actual, pero todavia no la convierte en un centro de control.

Resultado esperado:
Una vista unica donde ver que esta pasando, por que y que acciones tienen sentido ahora mismo.

Capacidades:

- decision actual y razones ordenadas por impacto
- riesgos abiertos
- cambios recomendados esta semana
- sesiones a priorizar y a evitar
- accesos directos a acciones operativas

Cambios probables:

- nueva composicion de datos en backend a partir de `coach_decision.json`
- panel de acciones con deep links a semana, dia, detalle o replanificacion

Criterios de aceptacion:

- la pagina reduce la necesidad de visitar varias vistas para decidir
- al menos una accion operativa importante se puede ejecutar desde esta vista

### 5. Seguimiento de molestias y riesgo

Problema:
La informacion de periostio existe, pero esta repartida y sin una lectura temporal potente.

Resultado esperado:
La web debe advertir antes, no solo describir despues.

Capacidades:

- timeline de dolor y molestias
- tendencias por 7 y 28 dias
- correlacion con tipos de sesion, volumen y zapatillas
- alertas de riesgo y reglas de proteccion

Cambios probables:

- nueva agregacion temporal desde athlete tracker y feedback post-entreno
- visualizacion de tendencia y semaforos
- integracion con decision y replanificacion

Criterios de aceptacion:

- el usuario ve si una molestia esta subiendo o bajando
- el sistema puede sugerir proteccion antes de empeorar

### 6. Semana operativa mas accionable

Problema:
La semana actual se lee bien, pero todavia no actua como tablero principal de ejecucion.

Resultado esperado:
La vista semanal debe funcionar como cockpit de la semana.

Capacidades:

- objetivo de la semana en una frase
- foco de cada sesion
- carga total prevista
- progreso semanal en vivo
- semaforo de cumplimiento semanal
- accesos rapidos a mover, ajustar o cerrar sesiones

Cambios probables:

- enriquecimiento de `week.rows` con contexto operativo
- nuevas acciones desde la propia vista semanal

Criterios de aceptacion:

- el usuario puede gobernar la semana sin saltar continuamente de pantalla
- la semana deja claro que es obligatorio, flexible o prescindible

### 7. Insights de progreso reales

Problema:
Existen metricas y checkpoints, pero falta narrativa de progreso comparativa.

Resultado esperado:
Que el usuario entienda si esta mejorando y en que dimension.

Capacidades:

- evolucion de ritmo, FC, RPE y cumplimiento
- comparables de sesiones similares
- progreso por bloque
- lectura "mejor/igual/peor que hace 4 semanas"
- estimaciones actualizadas con explicacion simple

Cambios probables:

- agregadores historicos nuevos
- modulos de tendencia y comparables en dashboard/completados

Criterios de aceptacion:

- los insights responden preguntas de progreso, no solo muestran numeros
- cada insight incluye contexto interpretable

### 8. Preparacion de carrera

Problema:
La vista de carreras es todavia estatica y no acompana la fase previa a competir.

Resultado esperado:
La carrera debe pasar de ser un dato a ser un flujo de preparacion.

Capacidades:

- countdown operativo
- estrategia de ritmo
- checklist pre-carrera
- vigilancia del taper
- prediccion de tiempo objetivo segun forma actual
- resumen post-carrera conectado con la revision
- enlace al plan automatico de hidratacion y carga de hidratos

Cambios probables:

- nueva vista de detalle de carrera
- composicion de contexto desde plan, dashboard y sesiones recientes
- integracion con el motor de nutricion para mostrar horas, cantidades y recordatorios

Criterios de aceptacion:

- la web ayuda tanto antes como despues de competir
- la carrera objetivo se convierte en el centro narrativo del ciclo

### 10. Nutricion, hidratacion y suplementacion

Problema:
Hoy el sistema no genera un plan automatico de hidratacion, carga de hidratos ni suplementacion para competiciones o sesiones muy duras.

Resultado esperado:
El sistema agentico debe preparar automaticamente protocolos consultables en la web para competiciones y recomendar que tomar antes, durante y despues en entrenamientos exigentes.

Alcance funcional:

- plan automatico de hidratacion previo a competiciones
- plan automatico de carga de hidratos previo a competiciones
- visualizacion web del protocolo con fechas, horas, tomas y notas
- recomendaciones antes, durante y despues para sesiones muy duras
- reglas especificas para entrenos como `10x1000`, tiradas muy largas o sesiones equivalentes por duracion/carga
- soporte de catalogo de suplementacion extensible

Suplementacion inicial conocida:

- creatina
- proteina
- maltodextrina
- fructosa
- electrolitos Evolytes
- SUB9 PRO SALTS ELECTROLYTES con 40 mg de cafeina

Requisitos de arquitectura:

- el modelo de suplementacion no debe quedar hardcodeado a estos seis productos
- debe existir un catalogo ampliable con tipo, objetivos, restricciones, cafeina, sodio, hidratos y formato
- las recomendaciones deben vivir en el sistema agentico y exponerse en la web, no duplicarse en dos logicas separadas

Enfoque tecnico recomendado:

- crear una capa de datos de suplementacion configurable
- derivar protocolos pre-carrera usando fecha, hora de salida, distancia, duracion estimada y clima si existiera
- derivar recomendaciones para sesiones exigentes usando tipo de sesion, duracion estimada y carga esperada
- exponer el resultado en detalle de carrera, detalle de sesion y semana operativa cuando aplique

Salidas esperadas:

- protocolo pre-carrera con fechas y horas concretas
- plan de carga de hidratos por tramo temporal
- plan de hidratacion con sales cuando aplique
- recomendacion before/during/after para entrenos exigentes
- notas de precaucion sobre cafeina, tolerancia y pruebas en entrenamiento

Superficies de producto:

- sistema agentico: genera y actualiza el protocolo automaticamente
- web carreras: muestra el protocolo completo de competicion
- web planificados: muestra recomendaciones para sesiones exigentes
- web dashboard o centro de decisiones: destaca proximos protocolos activos

Cambios probables:

- nuevo modelo de datos para suplementos y protocolos
- nuevas reglas del motor para competiciones y entrenamientos exigentes
- nuevas vistas o modulos en carreras y entrenamientos planificados
- integracion posterior con recordatorios o notificaciones si interesa

Criterios de aceptacion:

- toda competicion futura relevante puede mostrar su protocolo automaticamente
- un entreno clasificado como muy duro muestra recomendacion antes/durante/despues
- el sistema permite anadir nueva suplementacion sin redisenar el modelo
- la web muestra claramente fechas, horas, cantidades y observaciones

### 9. `/chat` web conectado al OpenCode remoto actual

Problema:
El usuario ya puede hablar con OpenCode por Telegram, pero la web no ofrece esa conversacion dentro del mismo producto.

Resultado esperado:
Una ruta `/chat` dentro de la web que permita conversar con OpenCode desde el navegador usando la misma base operativa y de sesiones que hoy usa Telegram.

Alcance funcional:

- vista `/chat` protegida por la autenticacion web actual
- caja de mensaje, historial visible y estado de "procesando"
- continuidad de sesion por usuario web
- selector de modelo equivalente al flujo actual
- opcion de nueva sesion y reset de sesion
- bloqueo de acciones sensibles con confirmacion, alineado con Telegram

Enfoque tecnico recomendado:

- no enrutar el chat a traves de Telegram
- reutilizar `OpenCodeBridge` como capa de ejecucion
- reutilizar `SessionStore` y la configuracion `opencode_remote`
- crear una identidad de sesion propia para web, separada de `chat_id` de Telegram
- mantener el mismo comportamiento de `attach` al servidor y fallback local

Arquitectura propuesta:

- `GET /chat`: render de la pagina de chat
- `POST /chat/messages`: enviar mensaje y devolver respuesta
- `POST /chat/session/reset`: olvidar sesion actual
- `POST /chat/model`: cambiar modelo activo del usuario web
- almacenamiento de historial UI en fichero local o estado simple por usuario

Decisiones de producto clave:

- la sesion web debe ser independiente de la sesion Telegram por defecto
- el historial visible en web no tiene por que ser el historial completo de OpenCode; puede ser un historico UI resumido
- la confirmacion de acciones sensibles debe mantenerse

Riesgos y mitigaciones:

- latencia alta: mostrar estado de procesamiento y timeouts comprensibles
- respuestas largas: truncado visual y opcion de expandir
- concurrencia: un lock por usuario web, igual que en Telegram
- seguridad: usar la autenticacion web existente y evitar exponer logs internos

Criterios de aceptacion:

- el usuario puede abrir `/chat`, mandar mensajes y mantener contexto entre mensajes
- una accion sensible requiere confirmacion antes de ejecutarse
- si `--attach` falla o no responde, el bridge conserva el fallback local sin romper la UX

## Orden recomendado de ejecucion

1. `/chat` web
2. Check-in diario rapido
3. Replanificacion real desde la web
4. Semana operativa mas accionable
5. Comparativa plan vs realidad
6. Centro de decisiones del coach
7. Seguimiento de molestias y riesgo
8. Insights de progreso reales
9. Nutricion, hidratacion y suplementacion
10. Preparacion de carrera

## Por que este orden

- `/chat` aporta un salto de utilidad transversal con poca duplicacion tecnica porque puede reutilizar el bridge actual.
- check-in y replanificacion cierran el bucle diario, que es donde mas valor se gana.
- las vistas agregadas y de analisis tienen mas sentido cuando ya existe una capa de accion mejor.
- nutricion e hidratacion deben entrar antes de la preparacion final de carrera para que el protocolo se pruebe tambien en entrenamientos duros.

## Dependencias tecnicas transversales

- definir un pequeno modelo de estado para acciones diarias y replanificaciones
- normalizar historicos por fecha para comparativas y tendencias
- mantener rutas nuevas coherentes con la autenticacion actual de FastAPI
- verificar que la UX funcione bien en movil
- crear un catalogo extensible de suplementacion y un generador de protocolos por evento/sesion

## Indicadores de exito

- mas acciones resueltas desde la web sin salir a Telegram o ficheros
- menos sesiones marcadas como "no pude" sin alternativa posterior
- mayor cobertura de feedback diario y post-entreno
- mayor claridad sobre cumplimiento del plan y riesgo de lesion
- mayor claridad operativa sobre que tomar y cuando antes de competir o en sesiones exigentes
