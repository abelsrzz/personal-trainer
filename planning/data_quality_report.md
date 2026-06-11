# Garmin Data Quality Report

- Fecha de analisis: `2026-06-11`
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
- Resting HR: `53.0`
- Training status: `{'userId': 137864769, 'mostRecentVO2Max': {'userId': 137864769, 'generic': {'calendarDate': '2026-06-10', 'vo2MaxPreciseValue': 45.9, 'vo2MaxValue': 46.0, 'fitnessAge': None, 'fitnessAgeDescription': None, 'maxMetCategory': 0}, 'cycling': None, 'heatAltitudeAcclimation': {'calendarDate': '2026-06-11', 'altitudeAcclimationDate': '2026-06-11', 'previousAltitudeAcclimationDate': '2026-06-11', 'heatAcclimationDate': '2026-06-11', 'previousHeatAcclimationDate': '2026-06-10', 'altitudeAcclimation': 0, 'previousAltitudeAcclimation': 0, 'heatAcclimationPercentage': 1, 'previousHeatAcclimationPercentage': 2, 'heatTrend': 'DEACCLIMATIZING', 'altitudeTrend': None, 'currentAltitude': 0, 'previousAltitude': 0, 'acclimationPercentage': 0, 'previousAcclimationPercentage': 0, 'altitudeAcclimationLocalTimestamp': '2026-06-11T22:19:24.0'}}, 'mostRecentTrainingLoadBalance': {'userId': 137864769, 'metricsTrainingLoadBalanceDTOMap': {'3621896103': {'calendarDate': '2026-06-11', 'deviceId': 3621896103, 'monthlyLoadAerobicLow': 955.29346, 'monthlyLoadAerobicHigh': 711.74243, 'monthlyLoadAnaerobic': 311.98096, 'monthlyLoadAerobicLowTargetMin': 396, 'monthlyLoadAerobicLowTargetMax': 1048, 'monthlyLoadAerobicHighTargetMin': 800, 'monthlyLoadAerobicHighTargetMax': 1453, 'monthlyLoadAnaerobicTargetMin': 217, 'monthlyLoadAnaerobicTargetMax': 652, 'trainingBalanceFeedbackPhrase': 'AEROBIC_HIGH_SHORTAGE', 'primaryTrainingDevice': True}}, 'recordedDevices': [{'deviceId': 3621896103, 'imageURL': 'https://res.garmin.com/en/products/010-02969-10/v/cf-sm-2x3.png', 'deviceName': 'Forerunner 970', 'category': 0}]}, 'mostRecentTrainingStatus': {'userId': 137864769, 'latestTrainingStatusData': {'3621896103': {'calendarDate': '2026-06-11', 'sinceDate': '2026-06-02', 'weeklyTrainingLoad': None, 'trainingStatus': 5, 'timestamp': 1781209164000, 'deviceId': 3621896103, 'loadTunnelMin': None, 'loadTunnelMax': None, 'loadLevelTrend': None, 'sport': 'RUNNING', 'subSport': 'GENERIC', 'fitnessTrendSport': 'RUNNING', 'fitnessTrend': 2, 'trainingStatusFeedbackPhrase': 'RECOVERY_2', 'trainingPaused': False, 'acuteTrainingLoadDTO': {'acwrPercent': 16, 'acwrStatus': 'LOW', 'acwrStatusFeedback': 'FEEDBACK_1', 'dailyTrainingLoadAcute': 219, 'maxTrainingLoadChronic': 690.0, 'minTrainingLoadChronic': 368.0, 'dailyTrainingLoadChronic': 460, 'dailyAcuteChronicWorkloadRatio': 0.4}, 'primaryTrainingDevice': True}}, 'recordedDevices': [{'deviceId': 3621896103, 'imageURL': 'https://res.garmin.com/en/products/010-02969-10/v/cf-sm-2x3.png', 'deviceName': 'Forerunner 970', 'category': 0}], 'showSelector': False, 'lastPrimarySyncDate': '2026-06-11'}, 'heatAltitudeAcclimationDTO': None}`
- Sleep score: `-`

## Mejoras Sugeridas

- Integrar HRV reciente en la decision de carga y en el dashboard.
- Usar training readiness para bloquear progresiones cuando Garmin marque baja preparacion.
- Comparar resting HR reciente con baseline para detectar fatiga o deriva.
- Traducir training status a una señal visible de forma y tolerancia de carga.

## Gaps

- sleep
- running_tolerance
