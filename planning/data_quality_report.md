# Garmin Data Quality Report

- Fecha de analisis: `2026-05-12`
- Ultima actividad importada: `2026-05-09`
- Ultimo daily importado: `2026-05-12`

## Cobertura

- `activities`: `yes`
- `daily_metrics`: `yes`
- `hrv`: `yes`
- `training_readiness`: `no`
- `resting_heart_rate`: `yes`
- `training_status`: `yes`
- `sleep`: `no`
- `running_tolerance`: `no`

## Snapshot Diario Disponible

- HRV: `137864769.0`
- Training readiness: `-`
- Resting HR: `55.0`
- Training status: `{'userId': 137864769, 'mostRecentVO2Max': None, 'mostRecentTrainingLoadBalance': None, 'mostRecentTrainingStatus': None, 'heatAltitudeAcclimationDTO': None}`
- Sleep score: `-`

## Mejoras Sugeridas

- Integrar HRV reciente en la decision de carga y en el dashboard.
- Comparar resting HR reciente con baseline para detectar fatiga o deriva.
- Traducir training status a una señal visible de forma y tolerancia de carga.

## Gaps

- training_readiness
- sleep
- running_tolerance
