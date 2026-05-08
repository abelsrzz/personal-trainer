# Coaching Playbook

## Purpose

Codify how the system prescribes training, not only which files it reads.

This file is the default decision policy for weekly planning, workout creation and replanning.

## Global Priorities

1. Protect continuity first.
2. Protect the left shin before chasing ideal workout density.
3. Build aerobic durability before demanding race-specific pace.
4. Use current evidence, not declared long-term goal pace, to prescribe quality.
5. Prefer the minimum effective dose that matches the intended stimulus.

## Athlete-Specific Baseline

- Current main project target is a 10k, but the workout library is multi-distance and distance-specific logic must still be respected.
- Current limiter is aerobic durability and repeatability, not isolated short-rep speed.
- Easy running must stay controlled by heart rate while the athlete is rebuilding consistency.
- The shin is a hard constraint: any progression is only valid when the next-morning response stays stable.
- `35:00` is aspirational until checkpoints support it.

## Default Prescription Logic

When planning a week or selecting a workout, decide in this order:

1. athlete availability and race calendar
2. coach color from `planning/coach_decision.md`
3. shin response from `athlete/shin_tracker.yaml`
4. active block intent from `planning/master_plan.md` and `planning/blocks/`
5. recent training absorption from completed reviews
6. target distance family from `training/planned/workouts/library_run_templates.yaml`
7. exact workout family and variant

## Stimulus Hierarchy By Phase

### Block 1

- Prioritize recovery, easy aerobic, strides only if the shin is quiet, short hills only if very low risk, and light steady or broken tempo.
- Avoid dense VO2max and hard race-specific sessions.

### Block 2

- Prioritize easy aerobic, long run development, aerobic steady work, progressions and early threshold.
- Use fartlek or economy work as support, not as the backbone.

### Block 3

- Prioritize threshold, cruise intervals, tempo blocks, strength endurance and fatigue resistance.
- Introduce distance-specific work only if threshold control is already stable.

### Block 4

- Prioritize 10k-specific work from current evidence, keeping threshold and aerobic support alive.
- VO2max is allowed if it serves the 10k block and recovery remains stable.

### Block 5

- Prioritize the final specific rhythm band, sharpening and repeatability without accumulating hidden fatigue.
- Sessions should build confidence, not just suffering.

### Block 6

- Reduce fatigue, preserve rhythm and avoid any session that needs more recovery than it gives back.

## Distance Logic

### 5k

- Main use: support power, economy and short-race ability.
- Choose 5k sessions when the athlete needs VO2max, economy or speed support that can later transfer to 10k.
- Do not overuse if the athlete already shows short-rep speed but poor aerobic durability.

### 10k

- Main use: target-specific development for the project.
- Threshold and controlled sustained work remain the backbone until the athlete earns denser 10k pace sessions.
- Use 10k-specific continuous work only after repeated success in shorter 10k-specific reps.

### 21k

- Main use: raise sustainable speed and fatigue resistance.
- Half-marathon style work is often a bridge between threshold work and harder 10k specificity.

### Marathon

- Main use: build durability, long-run quality and metabolic economy.
- Marathon-specific sessions are secondary in this project, but useful to support aerobic robustness and long quality runs.

## Progression Rules

- Progress only one main variable at a time: volume, rep length, rep count or recovery density.
- Repeat a successful session family before escalating to a harsher one if current consistency is still fragile.
- Prefer extending a known-good family over introducing an unrelated hard session.
- Keep at most two true quality sessions per week.
- Long-run quality only counts as a true quality day if it includes meaningful sustained work.

## Regression Rules

Reduce load or simplify the session when any of these happens:

- shin pain rises above the green band
- next-morning shin response worsens
- easy heart rate control deteriorates
- threshold pace is no longer repeatable at the intended control
- completed reviews show excessive fatigue cost for modest benefit
- sleep, soreness or life stress make the planned density unnecessary risk

Regression should usually happen by:

1. removing pace-specific work first
2. reducing rep count or total quality volume
3. changing the workout family to a lower-cost sibling
4. replacing quality with easy running or rest if needed

## Rules For Repeating, Deriving Or Discarding Sessions

Repeat a session family when:

- execution was good but still not easy enough to justify progression
- the athlete needs more exposure to the same rhythm skill
- the block objective is not yet fully absorbed

Derive a session when:

- the same stimulus is still correct but the dosage should change
- the athlete needs a shorter or longer version of a proven workout
- coach color is `yellow` and the same family must be preserved with lower cost

Discard a session family for the current cycle phase when:

- it repeatedly creates excess fatigue for the return
- it conflicts with the current limiter
- it only looks good on paper because of the long-term goal pace

## Rules For Tests And Tune-Up Races

- Use tests to recalibrate, not to prove bravery.
- Prefer tests after stable weeks, not during residual fatigue.
- A tune-up race should change training paces only when the result aligns with recent training and the execution context was normal enough.
- One surprisingly good result is not enough to justify a large jump in prescription.

## Completed Workout Interpretation

- A good session is one that delivers the intended stimulus at an appropriate cost.
- A session that is technically completed but leaves disproportionate fatigue is not a green light for progression.
- A session that feels easy and leaves low residual fatigue may justify progression only if recent easy-running control also remains stable.

## Hard Constraints

- Never prescribe from stretch goal pace alone.
- Never hide intensity inside easy or recovery days.
- Never stack high-cost workouts just because the calendar allows it.
- Never treat a single fast workout as proof that the athlete is ready for a new capability band.
