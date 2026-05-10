# RunPilot Execution Plan

Esta carpeta es local y no se versiona.

## Objetivo

Convertir la investigacion de producto en un sistema ejecutable punto por punto para RunPilot.

## Archivos

- `product_improvement_plan.md`: plan completo de producto.
- `backlog.yaml`: fuente de verdad operativa con fases, puntos, prioridad y estado.
- `execution_board.md`: tablero manual de seguimiento.
- `next_step.md`: unico foco activo recomendado.

## Regla de ejecucion

1. Solo un punto debe estar en `in_progress` a la vez.
2. Antes de empezar un punto, actualizar `next_step.md`.
3. Al terminar un punto:
   - cambiar estado en `backlog.yaml`
   - anotar decision y resultado en `execution_board.md`
   - mover el siguiente punto viable a `next_step.md`
4. Si aparece trabajo nuevo, se anade a `backlog.yaml`, no se mezcla informalmente.

## Estados permitidos

- `pending`
- `in_progress`
- `blocked`
- `completed`
- `cancelled`

## Como usarlo en una sesion

1. Leer `next_step.md`.
2. Ejecutar solo ese punto.
3. Verificar resultado.
4. Actualizar `backlog.yaml` y `execution_board.md`.

## Criterio de priorizacion

1. Impacto sobre experiencia diaria del atleta.
2. Capacidad para convertir analisis en accion.
3. Reutilizacion sobre las capacidades existentes del repo.
4. Riesgo tecnico bajo o medio antes que apuestas grandes.
