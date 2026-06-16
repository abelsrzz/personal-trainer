# Migración a base de datos SQL dockerizada

Rama `docker`, reconstruida desde 0 (la rama anterior se archivó en el tag local
`archive/docker-pre-rebuild`, SHA `4e98279`).

## Objetivo

Pasar de almacenar los datos en archivos a almacenarlos en una base de datos
PostgreSQL dockerizada, manteniendo el 100% de la funcionalidad actual.

## Arquitectura: híbrido con dual-write

- **PostgreSQL 16** guarda los **datos estructurados de runtime**: perfil/salud/zonas
  del atleta, carreras, entrenamientos planificados, actividades/reviews/feedback
  completados, y todo `system/state/*.json` (athlete_state, contextos, frescura,
  salud de automatización, feeds, colas de acciones/replans/checkins).
- **Se quedan como archivos** (por diseño): los imports crudos de Garmin
  (`training/completed/imports/garmin/**`, ~151 MB), el conocimiento estático
  (`planning/blocks`, playbooks, matrices, prompts) y los `.md` narrativos
  (master_plan, semanas) que edita el agente.
- **Dual-write**: la app escribe en archivo **y** en la DB. Los archivos siguen
  siendo el checkout git que el agente opencode lee, edita y `commit`/`push`.
- **Reconciliación**: un sidecar ejecuta el importador idempotente cada 5 min
  para capturar a los escritores que no pasan por `legacy_support` (daemon de
  Garmin, pipeline semanal) y las ediciones de archivos del agente.

Por qué no DB pura: el agente opencode opera sobre el repo real (hace commits y
push). Los archivos no pueden desaparecer.

## Componentes nuevos

| Archivo | Rol |
|---|---|
| `scripts/storage/db.py` | DSN, toggle `STORAGE_BACKEND`, conexión, `wait_for_database` |
| `scripts/storage/schema.py` | DDL Postgres (solo runtime estructurado) |
| `scripts/storage/runtime.py` | helpers de lectura/upsert (artifacts + colecciones + listas tipadas) |
| `scripts/storage/migrate_files_to_sql.py` | importador idempotente + `mirror_file`/`mirror_delete`/`prune` |
| `Dockerfile` | imagen app (python:3.13-slim, usuario `app`, tini, git) |
| `docker-compose.yml` | db, migrate, reconcile, opencode, web, garmin, telegram |
| `.env.example` | plantilla de configuración |

Puntos de enganche en `scripts/web_v2/legacy_support.py`: `write_json` y
`write_yaml` llaman a `_mirror_to_sql()` (no-op salvo `STORAGE_BACKEND=sql`).

## Cómo ejecutar (local)

```bash
cp .env.example .env          # rellenar secretos
docker compose build
docker compose run --rm migrate   # importar archivos -> SQL (con --validate)
docker compose up -d
docker compose ps
curl http://127.0.0.1:8090/healthz
```

Migración manual / reconciliación:

```bash
# dry-run (no escribe)
python scripts/storage/migrate_files_to_sql.py
# aplicar + validar + podar huérfanos
python scripts/storage/migrate_files_to_sql.py --apply --validate --prune
```

## Estado

Hecho y verificado contra Postgres 16 real:
- [x] Esquema + importador (188 archivos estructurados, validación OK, idempotente).
- [x] Dual-write desde `legacy_support.write_json/write_yaml` (probado).
- [x] `mirror_file` / `mirror_delete` / `--prune`.
- [x] Dockerfile + docker-compose + .env.example + .dockerignore.

Pendiente:
- [ ] **Networking de opencode en contenedor**: apuntar el bridge a
  `http://opencode:4096` vía env (`OPENCODE_SERVER_URL`). En `main`,
  `legacy_support.load_web_chat_remote_config` y el bot leen `telegram/bot_config.yaml`;
  hay que añadir fallback a variables de entorno o fijar `server_url` en el config.
- [ ] **Lecturas DB-first** (mejora): hoy las lecturas son file-first (siempre
  frescas). Pasar las vistas de lista (calendario/plan) a `runtime.list_*` para
  leer de la DB. No bloquea la paridad porque el dato ya vive en SQL.
- [ ] **Pipeline de deploy** (GitLab CI): job docker a
  `root@192.168.2.81:/opt/personal-trainer` — build, migrate, `docker compose up -d`.
- [ ] **Migración del servidor en ejecución**: importar el dato vivo de archivos
  a la DB una vez, sembrar tokens de Garmin (`/home/app/.garminconnect`) y el
  binario opencode en sus volúmenes, parar los servicios systemd/nohup viejos
  antes del corte.
- [ ] **Checklist de paridad** end-to-end (tests).

## Checklist de paridad (a verificar en Docker)

- Acciones web: marcar hecho, saltar, alternativa, replanificar.
- Replanificación de rango (web + runtime).
- Subida/sync de workouts a Garmin sin duplicados; borrado/reprogramación.
- Feedback post-entreno desde web.
- Telegram end-to-end: mensaje -> opencode -> respuesta.
- Fallback Gemini cuando OpenAI/OpenCode falla.
- Pipeline semanal completo.
- Post-workout refresh tras actividad real.
