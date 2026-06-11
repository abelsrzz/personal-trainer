# Garmin Data Quality Report

- Fecha de analisis: `2026-05-19`
- Ultima actividad importada: `2026-06-10`
- Ultimo daily importado: `2026-06-11`

## Cobertura

- `activities`: `yes`
- `daily_metrics`: `yes`
- `hrv`: `yes`
- `training_readiness`: `yes`
- `resting_heart_rate`: `yes`
- `training_status`: `yes`
- `sleep`: `no`
- `running_tolerance`: `no`

## Snapshot Diario Disponible

- HRV: `137864769.0`
- Training readiness: `137864769.0`
- Resting HR: `54.0`
- Training status: `{'userId': 137864769, 'mostRecentVO2Max': {'userId': 137864769, 'generic': {'calendarDate': '2026-05-16', 'vo2MaxPreciseValue': 45.9, 'vo2MaxValue': 46.0, 'fitnessAge': None, 'fitnessAgeDescription': None, 'maxMetCategory': 0}, 'cycling': None, 'heatAltitudeAcclimation': {'calendarDate': '2026-05-19', 'altitudeAcclimationDate': '2026-05-19', 'previousAltitudeAcclimationDate': '2026-05-19', 'heatAcclimationDate': '2026-05-19', 'previousHeatAcclimationDate': '2026-05-19', 'altitudeAcclimation': 0, 'previousAltitudeAcclimation': 0, 'heatAcclimationPercentage': 0, 'previousHeatAcclimationPercentage': 0, 'heatTrend': None, 'altitudeTrend': None, 'currentAltitude': 283, 'previousAltitude': 0, 'acclimationPercentage': 0, 'previousAcclimationPercentage': 0, 'altitudeAcclimationLocalTimestamp': '2026-05-19T23:56:11.0'}}, 'mostRecentTrainingLoadBalance': {'userId': 137864769, 'metricsTrainingLoadBalanceDTOMap': {'3621896103': {'calendarDate': '2026-05-19', 'deviceId': 3621896103, 'monthlyLoadAerobicLow': 899.479, 'monthlyLoadAerobicHigh': 935.847, 'monthlyLoadAnaerobic': 336.0453, 'monthlyLoadAerobicLowTargetMin': 393, 'monthlyLoadAerobicLowTargetMax': 1046, 'monthlyLoadAerobicHighTargetMin': 802, 'monthlyLoadAerobicHighTargetMax': 1455, 'monthlyLoadAnaerobicTargetMin': 217, 'monthlyLoadAnaerobicTargetMax': 652, 'trainingBalanceFeedbackPhrase': 'BALANCED', 'primaryTrainingDevice': True}}, 'recordedDevices': [{'deviceId': 3621896103, 'imageURL': 'https://res.garmin.com/en/products/010-02969-10/v/cf-sm-2x3.png', 'deviceName': 'Forerunner 970', 'category': 0}]}, 'mostRecentTrainingStatus': {'userId': 137864769, 'latestTrainingStatusData': {'3621896103': {'calendarDate': '2026-05-19', 'sinceDate': '2026-05-19', 'weeklyTrainingLoad': None, 'trainingStatus': 5, 'timestamp': 1779214810000, 'deviceId': 3621896103, 'loadTunnelMin': None, 'loadTunnelMax': None, 'loadLevelTrend': None, 'sport': 'RUNNING', 'subSport': 'GENERIC', 'fitnessTrendSport': 'RUNNING', 'fitnessTrend': 2, 'trainingStatusFeedbackPhrase': 'RECOVERY_2', 'trainingPaused': False, 'acuteTrainingLoadDTO': {'acwrPercent': 25, 'acwrStatus': 'LOW', 'acwrStatusFeedback': 'FEEDBACK_1', 'dailyTrainingLoadAcute': 371, 'maxTrainingLoadChronic': 850.5, 'minTrainingLoadChronic': 453.6, 'dailyTrainingLoadChronic': 567, 'dailyAcuteChronicWorkloadRatio': 0.6}, 'primaryTrainingDevice': True}}, 'recordedDevices': [{'deviceId': 3621896103, 'imageURL': 'https://res.garmin.com/en/products/010-02969-10/v/cf-sm-2x3.png', 'deviceName': 'Forerunner 970', 'category': 0}], 'showSelector': False, 'lastPrimarySyncDate': '2026-05-19'}, 'heatAltitudeAcclimationDTO': None}`
- Sleep score: `-`

## Mejoras Sugeridas

- Integrar HRV reciente en la decision de carga y en el dashboard.
- Usar training readiness para bloquear progresiones cuando Garmin marque baja preparacion.
- Comparar resting HR reciente con baseline para detectar fatiga o deriva.
- Traducir training status a una señal visible de forma y tolerancia de carga.

## Gaps

- sleep
- running_tolerance
