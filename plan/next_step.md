# Next Step

## Active Item

- `AP-02` Automatizar deteccion de actividades nuevas

## Why This Next

- `AP-01` ya deja definido el contrato de `post_workout_refresh`.
- El siguiente cuello de botella es disparar ese pipeline sin tener que ejecutar comandos manuales.
- Hace falta detectar actividades nuevas de forma local, fiable e idempotente.

## Expected Output

1. Trigger automatico local para nuevas actividades.
2. Estado persistente de ultima actividad vista y procesada.
3. Arranque automatico del pipeline sin comando manual.
4. Base segura para encadenar el resto del flujo post-entreno.

## Completion Check

- Existe trigger automatico local sin comando manual.
- El sistema detecta actividad nueva y arranca el pipeline.
