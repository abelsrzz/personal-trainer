# Coach Decision

- Fecha de analisis: `2026-05-13`
- Estado: `red`
- Accion: `reduce_or_replace_quality`
- Decision: Reducir carga inmediata: cambiar la proxima calidad por rodaje muy facil o descanso, y mantener FC capada.

## Motivos

- Revision reciente de alto riesgo: 2026-05-07 Rodaje 6 km + 4 rectas controladas.
- Subida de volumen semanal de 79% (14.7 -> 26.2 km entre semanas completas).
- El bloque activo prioriza reconstruccion, consistencia y tolerancia tisular antes de ritmos agresivos.
- El limitador principal declarado sigue siendo la durabilidad aerobica; la construccion debe respetarlo.
- La automatizacion prioriza como backbone de calidad: cruise_intervals, tempo_broken, tempo_continuous.

## Regla Operativa

- `green`: se puede mantener el plan y progresar poco.
- `yellow`: mantener sin subir carga; vigilar 2-3 sesiones.
- `red`: reducir o sustituir calidad por rodaje muy facil/descanso.
