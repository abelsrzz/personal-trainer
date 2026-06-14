# Running Coach Workspace

Workspace local para usar OpenCode como entrenador de running.

## Objetivo

- Mantener el perfil completo del atleta.
- Guardar carreras clasificadas como `S`, `A`, `B`, `C` o `D`, incluyendo desnivel aproximado.
- Construir un plan general basado en la unica carrera `S`.
- Desglosar el plan en bloques y semanas.
- Mantener `planning/weeks/semana_actual.md` como fuente activa semanal.
- Importar actividades reales y, mas adelante, sincronizar con Garmin.

## Reglas clave

- Solo puede existir una carrera con prioridad `S`.
- Las carreras `A`, `B`, `C` y `D` pueden ser multiples.
- La semana operativa siempre va de lunes a domingo.
- Cada domingo se genera la siguiente semana a partir del bloque activo, lo hecho la semana previa y las carreras cercanas.
- La semana anterior se archiva en `planning/weeks/archived/<ano>/`.

## Estructura

- `athlete/`: perfil, zonas, salud, zapatillas e historial.
- `races/`: carreras por ano.
- `planning/`: plan general, bloques y semanas.
- `training/`: entrenamientos planificados, importados y revisados.
- `garmin/`: mapeos y log de sincronizacion.
- `scripts/`: automatizaciones futuras.
- `system/`: plantillas, prompts y esquemas internos.
- `.agents/`: memoria operativa local para futuras sesiones de IA.

## Primera carga de datos

Rellena `INPUT_DATOS_REALES.md` en la raiz del proyecto.

## Flujo De Uso

1. Se genera o actualiza `planning/weeks/semana_actual.md`.
2. Despues de cada entrenamiento, me pasas lo realizado o importamos desde Garmin.
3. Para entrenamientos planificados hechos con Garmin, ejecuta `python scripts/garmin/review_planned_session.py --date YYYY-MM-DD` para importar, comparar y generar la revision automaticamente.
4. El entrenamiento se revisa con nota numerica, semaforo y comentario tecnico.
5. Si la ejecucion o la fatiga lo justifican, se replanifica la semana actual.
6. La siguiente semana se prepara sin pisar la activa, y se activa cuando toque.
7. Al activar una semana preparada, la semana saliente se archiva automaticamente.
8. Cada vez que se active o actualice `planning/weeks/semana_actual.md`, se genera el PDF y se envia por Telegram.

## Garmin V1

El conector inicial esta en `scripts/garmin/sync_garmin.py`.

Preparacion local:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp garmin/local_credentials.yaml.example garmin/local_credentials.yaml
```

Importar actividades recientes:

```bash
python scripts/garmin/sync_garmin.py import-activities --days 14 --limit 30
```

Importar y revisar automaticamente un entrenamiento planificado completado:

```bash
source .venv/bin/activate
python scripts/garmin/review_planned_session.py --date 2026-05-05
```

Salida generada:

- `training/completed/activities/<workout>.yaml`
- `training/completed/reviews/<workout>.md`
- `training/completed/reviews/<workout>.analysis.json`

Importar metricas diarias para enriquecer recuperacion y estado:

```bash
python scripts/garmin/sync_garmin.py import-daily --days 14
```

Trigger automatico post-entreno recomendado:

```bash
source .venv/bin/activate
python scripts/garmin/post_workout_refresh.py
```

Daemon automatico en bucle para dejarlo siempre escuchando nuevas sesiones Garmin:

```bash
source .venv/bin/activate
python scripts/garmin/post_workout_refresh_daemon.py --interval-seconds 300
```

Rebuild manual del flujo heredado por fecha:

```bash
source .venv/bin/activate
python scripts/garmin/coach_sync.py --date YYYY-MM-DD
```

Este comando importa actividades Garmin, intenta importar metricas diarias, intenta sincronizar perfil Garmin del atleta, revisa el entrenamiento planificado del dia si existe y genera:

- `athlete/status_dashboard.md`
- `planning/coach_decision.md`
- `planning/coach_decision.json`

Para trabajar solo con datos ya importados, sin conectar con Garmin:

```bash
python scripts/garmin/coach_sync.py --date YYYY-MM-DD --skip-garmin
```

Evaluar el estado del atleta y los gates del objetivo `35:00`:

```bash
python scripts/garmin/coach_engine.py --as-of YYYY-MM-DD --days 28
```

Sincronizar tambien perfil del atleta, FC reposo, FC maxima, VO2max y material desde Garmin:

```bash
python scripts/garmin/sync_garmin.py import-athlete-profile
python scripts/garmin/athlete_sync.py
```

`coach_sync.py` sigue siendo util como rebuild manual, pero el camino por defecto tras un entreno completado es `post_workout_refresh.py` o su timer `systemd`.

Plantillas reutilizables para convertir en sesiones fechadas:

- `training/planned/workouts/library_run_templates.yaml`

Contexto de coaching que el sistema debe usar por defecto:

- `planning/context_automation_policy.md`
- `planning/coaching_playbook.md`
- `planning/workout_knowledge.yaml`
- `planning/workout_template_knowledge_map.yaml`
- `planning/session_selection_matrix.yaml`
- `planning/workout_evaluation_rules.md`
- `athlete/response_profile.yaml`

## Memoria Persistente

Puntos de entrada recomendados para futuras sesiones:

1. `AGENT.md`
2. `.agents/README.md`
3. `.agents/memory/project_snapshot.md`
4. `.agents/workflows/weekly_coaching_cycle.md`

## PDF Y Telegram

Configuracion local:

```bash
cp telegram/bot_config.yaml.example telegram/bot_config.yaml
```

Generar y enviar el PDF actual:

```bash
source .venv/bin/activate
python scripts/notifications/semana_pdf_telegram.py send-now
```

Vigilar cambios en `semana_actual.md` y enviar al detectar modificaciones:

```bash
source .venv/bin/activate
python scripts/notifications/semana_pdf_telegram.py watch --interval 30
```

## Planificacion Semanal Automatizada

Pipeline seguro para preparar y activar la siguiente semana:

```bash
source .venv/bin/activate
python scripts/system/weekly_planning_pipeline.py status
python scripts/system/weekly_planning_pipeline.py plan-next --source manual
python scripts/system/weekly_planning_pipeline.py activate-next --source manual
```

Reglas del pipeline:

- `plan-next` prepara la siguiente semana en `planning/weeks/prepared/<year>/` sin tocar `planning/weeks/semana_actual.md`
- si la siguiente semana ya estaba preparada, no la pisa salvo que se fuerce una regeneracion
- `activate-next` archiva la semana activa, mueve la preparada a `semana_actual.md`, envia el PDF por Telegram e intenta sincronizar en Garmin los workouts fechados de esa semana que hayan cambiado

Ejemplos `systemd`:

- `deploy/systemd/weekly-planning-pipeline.service.example`
- `deploy/systemd/weekly-planning-pipeline.timer.example`

## OpenCode Remoto Por Telegram

El proyecto puede exponerse como una sesion remota de OpenCode usando el mismo bot de Telegram.

Preparacion:

```bash
source .venv/bin/activate
pip install -r requirements.txt
cp telegram/bot_config.yaml.example telegram/bot_config.yaml
python scripts/telegram/opencode_bot.py --check-config
```

Servidor OpenCode:

```bash
opencode serve --hostname 127.0.0.1 --port 4096
```

Bot Telegram:

```bash
source .venv/bin/activate
python scripts/telegram/opencode_bot.py
```

Comandos utiles desde Telegram:

- `/status`: muestra `planning/coach_decision.md`.
- `/dashboard`: muestra `athlete/status_dashboard.md`.
- `/today`: devuelve el briefing actual del dia.
- `/brief`: devuelve el briefing del entrenador bajo demanda.
- `/pre`: devuelve la decision pre-entreno de hoy.
- `/model`: muestra el modelo activo.
- `/model openai/gpt-5.4`: cambia el modelo del chat.
- `/model reset`: vuelve al modelo por defecto.
- `/sync`: ejecuta sincronizacion completa Garmin + estado del entrenador.
- `/sync_local`: recalcula estado local sin contactar Garmin.
- `/sync_planned`: reconcilia entrenamientos futuros con Garmin.
- `/health`: muestra `system/state/automation_health.md`.
- `/jobs`: muestra el estado de las automatizaciones.
- `/week`: muestra la semana activa; en la web redirige a `planned-workouts?view=week`.
- `/pdf_week`: genera y envia el PDF semanal.
- `/git`: muestra `git status --short`.
- cualquier otro mensaje se envia a OpenCode.

El modelo por defecto del servicio remoto es `openai/gpt-5.4` con razonamiento default de OpenCode. El bot no pasa `--variant`, asi que no fuerza razonamiento alto.

Ejemplos de servicios `systemd`:

- `deploy/systemd/opencode-server.service.example`
- `deploy/systemd/opencode-telegram-bot.service.example`
- `deploy/systemd/running-coach-automation.service.example`
- `deploy/systemd/running-coach-automation.timer.example`
- `deploy/systemd/running-coach-morning-brief.service.example`
- `deploy/systemd/running-coach-morning-brief.timer.example`
- `deploy/systemd/post-workout-refresh.service.example`
- `deploy/systemd/post-workout-refresh.timer.example`

## Despliegue Desde GitLab

El repositorio incluye `.gitlab-ci.yml` para desplegar automaticamente cada cambio en `main` a una maquina remota por SSH.

Comportamiento del pipeline:

- copia el repositorio al destino con `rsync`
- lo deja en `DEPLOY_PATH` con valor por defecto `/opt/personal-trainer`
- ejecuta un comando opcional post-copia
- reinicia la aplicacion con el comando que definas

Variables CI/CD que debes configurar en GitLab:

- `DEPLOY_HOST`: IP o nombre DNS de la maquina destino
- `DEPLOY_PORT`: puerto SSH, opcional, por defecto `22`
- `DEPLOY_USER`: usuario SSH con permisos sobre `DEPLOY_PATH` y el reinicio
- `DEPLOY_SSH_PRIVATE_KEY`: clave privada usada por el runner para conectarse
- `DEPLOY_SSH_KNOWN_HOSTS`: opcional pero recomendado; salida de `ssh-keyscan -H <host>`
- `DEPLOY_PATH`: opcional; por defecto `/opt/personal-trainer`
- `DEPLOY_POST_SYNC_COMMAND`: opcional; por ejemplo `./start_server.sh install`
- `DEPLOY_RESTART_COMMAND`: obligatorio; por ejemplo `systemctl restart opencode-server` o `./start_server.sh restart`

Ejemplos de reinicio:

```bash
systemctl restart opencode-server
systemctl restart opencode-web
./start_server.sh restart
```

Polling automatico post-entreno:

```bash
source .venv/bin/activate
python scripts/garmin/post_workout_refresh.py
```

Este comando:

- importa actividades Garmin recientes
- detecta actividades nuevas no vistas antes
- persiste estado en `system/state/post_workout_refresh_state.json`
- dispara el pipeline post-entreno para cada fecha nueva detectada

En despliegue local, la via recomendada es usar el timer `systemd` de ejemplo para ejecutarlo cada `5 min`.

Modo servicio recomendado:

```bash
source .venv/bin/activate
python scripts/system/automation_hub.py status
python scripts/system/action_runtime.py run service_sync --payload-json '{}'
python scripts/notifications/coach_messages.py send-morning-brief --force
```

El servicio continuo esperado combina:

- `opencode serve` para el canal remoto
- bot de Telegram
- `automation_hub.py run-due` cada pocos minutos
- briefing diario por Telegram cada manana
- sincronizacion recurrente Garmin y reconciliacion de entrenos futuros
- mensaje post-entreno cuando se detecta actividad nueva y se actualiza el estado

## Portal Web

El proyecto incluye una interfaz web operativa para consultar y accionar la capa diaria del entorno agentico.

Qué muestra la web actual:

- resumen ejecutivo del estado actual
- check-in diario, acciones sobre sesiones planificadas y replanificacion
- entrenamientos planificados en vistas `week`, `list` y `calendar`
- dashboard del atleta con la decision operativa y el progreso integrados
- entrenamientos completados y sus revisiones
- perfil del atleta, periostio y carreras
- planificacion semanal segura desde la web, con preparacion y activacion
- estado basico del sistema y chat web

Notas de estructura:

- `/planned-workouts` concentra la planificación futura.
- `/planned-workouts?view=week` es la vista semanal integrada.
- `/week` redirige a la vista semanal dentro de planificados.
- `/dashboard` integra tambien la lectura de `decision` y `progress`.
- `/decision` redirige a `/dashboard`.
- `/progress` redirige a `/dashboard`.

Dependencias:

```bash
source .venv/bin/activate
pip install -r requirements.txt
```

Credenciales minimas en archivo local del proyecto:

```bash
cp web_v2/web_config.yaml.example web_v2/web_config.yaml
```

Contenido esperado:

```yaml
web:
  username: abel
  password: cambia-esto
  secret: una-clave-de-sesion-larga
```

Tambien puedes usar variables de entorno si quieres sobreescribir el archivo:

```bash
export RUNNING_WEB_USERNAME=abel
export RUNNING_WEB_PASSWORD='cambia-esto'
export RUNNING_WEB_SECRET='una-clave-de-sesion-larga'
```

Lanzar la web:

```bash
source .venv/bin/activate
python -m uvicorn scripts.web_v2.app:app --app-dir . --host 127.0.0.1 --port 8090
```

Healthcheck:

```bash
curl http://127.0.0.1:8090/healthz
```

Integracion en el arranque global:

```bash
cp web_v2/web_config.yaml.example web_v2/web_config.yaml
./start_server.sh start
```

Variables opcionales:

- `RUNNING_WEB_HOST` por defecto `127.0.0.1`
- `RUNNING_WEB_PORT` por defecto `8090`
- `RUNNING_WEB_ENABLED=0` para no arrancar la web desde `start_server.sh`
- `POST_WORKOUT_REFRESH_ENABLED=1` para arrancar el detector automatico de nuevas actividades Garmin
- `POST_WORKOUT_REFRESH_INTERVAL_SECONDS=300` para controlar cada cuanto se consulta Garmin
- `RUNNING_WEB_USERNAME`, `RUNNING_WEB_PASSWORD` y `RUNNING_WEB_SECRET` pueden sobreescribir el fichero local

Servicio `systemd` de ejemplo:

- `deploy/systemd/opencode-web.service.example`
