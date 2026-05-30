# Completed Reviews

Evaluaciones y notas de entrenamientos realizados.

Despues de cada entrenamiento, la revision debe incluir:

- nota numerica
- semaforo
- comentario tecnico
- decision de mantener o replanificar la semana actual

Para entrenamientos planificados completados con Garmin, la revision puede generarse con:

```bash
source .venv/bin/activate
python scripts/garmin/review_planned_session.py --date YYYY-MM-DD
```
