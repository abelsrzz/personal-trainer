# Garmin Data Quality Report

- Fecha de analisis: `2026-06-15`
- Ultima actividad importada: `2026-06-10`
- Ultimo daily importado: `2026-06-15`

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

- HRV: `75.0`
- Training readiness: `-`
- Resting HR: `51.0`
- Training status: `{'userId': 137864769, 'mostRecentVO2Max': {'userId': 137864769, 'generic': {'calendarDate': '2026-06-10', 'vo2MaxPreciseValue': 45.9, 'vo2MaxValue': 46.0, 'fitnessAge': None, 'fitnessAgeDescription': None, 'maxMetCategory': 0}, 'cycling': None, 'heatAltitudeAcclimation': {'calendarDate': '2026-06-15', 'altitudeAcclimationDate': '2026-06-14', 'previousAltitudeAcclimationDate': '2026-06-14', 'heatAcclimationDate': '2026-06-14', 'previousHeatAcclimationDate': '2026-06-13', 'altitudeAcclimation': 0, 'previousAltitudeAcclimation': 0, 'heatAcclimationPercentage': 1, 'previousHeatAcclimationPercentage': 1, 'heatTrend': 'ACCLIMATIZED', 'altitudeTrend': None, 'currentAltitude': 0, 'previousAltitude': 0, 'acclimationPercentage': 0, 'previousAcclimationPercentage': 0, 'altitudeAcclimationLocalTimestamp': '2026-06-15T00:03:27.0'}}, 'mostRecentTrainingLoadBalance': {'userId': 137864769, 'metricsTrainingLoadBalanceDTOMap': {'3621896103': {'calendarDate': '2026-06-15', 'deviceId': 3621896103, 'monthlyLoadAerobicLow': 873.93115, 'monthlyLoadAerobicHigh': 571.0513, 'monthlyLoadAnaerobic': 232.5163, 'monthlyLoadAerobicLowTargetMin': 396, 'monthlyLoadAerobicLowTargetMax': 1048, 'monthlyLoadAerobicHighTargetMin': 800, 'monthlyLoadAerobicHighTargetMax': 1453, 'monthlyLoadAnaerobicTargetMin': 217, 'monthlyLoadAnaerobicTargetMax': 652, 'trainingBalanceFeedbackPhrase': 'AEROBIC_HIGH_SHORTAGE', 'primaryTrainingDevice': True}}, 'recordedDevices': [{'deviceId': 3621896103, 'imageURL': 'https://res.garmin.com/en/products/010-02969-10/v/cf-sm-2x3.png', 'deviceName': 'Forerunner 970', 'category': 0}]}, 'mostRecentTrainingStatus': {'userId': 137864769, 'latestTrainingStatusData': {'3621896103': {'calendarDate': '2026-06-15', 'sinceDate': '2026-06-02', 'weeklyTrainingLoad': None, 'trainingStatus': 5, 'timestamp': 1781501521000, 'deviceId': 3621896103, 'loadTunnelMin': None, 'loadTunnelMax': None, 'loadLevelTrend': None, 'sport': 'RUNNING', 'subSport': 'GENERIC', 'fitnessTrendSport': 'RUNNING', 'fitnessTrend': 2, 'trainingStatusFeedbackPhrase': 'RECOVERY_2', 'trainingPaused': False, 'acuteTrainingLoadDTO': {'acwrPercent': 8, 'acwrStatus': 'LOW', 'acwrStatusFeedback': 'FEEDBACK_1', 'dailyTrainingLoadAcute': 81, 'maxTrainingLoadChronic': 540.0, 'minTrainingLoadChronic': 288.0, 'dailyTrainingLoadChronic': 360, 'dailyAcuteChronicWorkloadRatio': 0.2}, 'primaryTrainingDevice': True}}, 'recordedDevices': [{'deviceId': 3621896103, 'imageURL': 'https://res.garmin.com/en/products/010-02969-10/v/cf-sm-2x3.png', 'deviceName': 'Forerunner 970', 'category': 0}], 'showSelector': False, 'lastPrimarySyncDate': '2026-06-15'}, 'heatAltitudeAcclimationDTO': None}`
- Sleep score: `-`

## Mejoras Sugeridas

- Integrar HRV reciente en la decision de carga y en el dashboard.
- Comparar resting HR reciente con baseline para detectar fatiga o deriva.
- Traducir training status a una señal visible de forma y tolerancia de carga.

## Gaps

- training_readiness
- sleep
- running_tolerance
