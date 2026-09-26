# Skill card: mock

A skill that moves nothing. It sleeps 5 seconds. It exists so the runner, the trial script, the log and the scoreboard can be rehearsed before any real skill exists.

```yaml
name: mock
version: 1
phrases:
  - "run the mock"
objects: []
layout: desk_v1
robot: none
cameras: []
backend: mock
policy: none
task_string: "Do nothing for five seconds"
timeout_s: 30
step_limit: default
confirm: required
precondition_text: "Nothing needed."
success_text: "The run ended without a stop."
```

## Success rule (binary)

The run reaches DONE on its own. A stop or a timeout is a fail.

## Start positions

3 x 3 grid, cells 1 to 9, drawn from `config/positions-seed.txt` in order. For the mock the cell is only written to the log.

## Known limits

- Does nothing. Scores from this card are rehearsal numbers, never published.

## Score history

| Date | Policy | Dataset | Episodes | Score /20 | Layout | Notes | Video |
|---|---|---|---|---|---|---|---|
| | | | | | | | |
