# How the brain works

Diagrams for people who want to learn from this build. They render on GitHub. To change one, edit the text block, there are no image files.

Dashed boxes are planned and not built yet. Solid boxes exist in this repo or in [jarvis-arm](https://github.com/Jarviswashere/jarvis-arm).

## 1. Where the runner sits

```mermaid
flowchart LR
    person["Person"] -->|"voice"| reachy["Reachy Mini<br>listens, talks, looks"]
    reachy --> llm["Conversation app<br>LLM with tools: run_skill, stop_skill, describe_scene"]
    llm -->|"HTTP, localhost"| runner["Skill runner<br>this repo"]
    keyboard["Keyboard in the runner window"] -->|"arm, disarm, stop"| runner
    runner -->|"spawns a process"| lerobot["lerobot-rollout<br>in jarvis-arm"]
    lerobot --> arm["Follower arm"]
    runner --> logs["runs.log and trial-log.csv"]
    logs --> board["SCOREBOARD.md"]
    estop{{"E-stop"}} ==>|"cuts 12V"| arm

    classDef planned stroke-dasharray: 5 5
    class reachy,llm,lerobot planned
```

What to notice:

- The LLM never touches the arm. It can only ask the runner. The runner decides.
- The runner never imports LeRobot. It starts it as a separate process, so a crash in one does not take the other down, and the two can be updated on their own.
- The keyboard has powers the LLM does not have. That asymmetry is the whole safety design.

## 2. The runner state machine

```mermaid
stateDiagram-v2
    [*] --> DISARMED

    state "Armed (a human pressed a)" as Armed {
        ARMED --> RUNNING: POST /run, all four checks pass
        RUNNING --> DONE: skill finished
        RUNNING --> STOPPED: stop from keyboard, HTTP or timeout
        RUNNING --> FAILED: error inside the skill
        DONE --> RUNNING: POST /run
        STOPPED --> RUNNING: POST /run
        FAILED --> RUNNING: POST /run
    }

    DISARMED --> Armed: key a, keyboard only
    Armed --> DISARMED: key d, POST /disarm, or 10 minutes idle
```

What to notice:

- There is no HTTP way into the armed state. `POST /arm` always answers 403. That is a rule enforced by code, not by a comment.
- Idle time counts only while no run is going. A run in progress is never cut by the idle timer. It is cut by its own timeout.
- Disarming during a run stops the run first. Disarm is always safe to call.

## 3. Can this run start

Every `POST /run` passes four checks. The first one that fails is the answer, with a sentence that says what to do.

```mermaid
flowchart TD
    req["POST /run {skill}"] --> a{"Armed?"}
    a -->|"no"| r1["409: press a in the runner window"]
    a -->|"yes"| b{"Preflight passed today?"}
    b -->|"no"| r2["409: run preflight.py, then press p"]
    b -->|"yes"| c{"No run in progress?"}
    c -->|"no"| r3["409: a run is already going"]
    c -->|"yes"| d{"E-stop reminder acknowledged?"}
    d -->|"no"| r4["409: press e in the runner window"]
    d -->|"yes"| e{"Skill known?"}
    e -->|"no"| r5["404: unknown skill, list of known ones"]
    e -->|"yes"| go["Start the skill in a thread<br>hard timeout from the skill card"]
```

What to notice:

- 409 means "not now", 404 means "no such thing". A caller, human or LLM, can tell the two apart.
- Two of the checks are things only a person can set, by pressing a key after doing something in the real world.

## 4. Four ways to stop, fastest first

All four must work. Each one is tested at the start of every session and the latency is written down.

```mermaid
flowchart LR
    e["1. Hardware e-stop<br>cuts 12V to both boards<br>arm goes limp at once"] --> k["2. Stop key or button<br>s or space in the runner window<br>freeze within 300 ms"]
    k --> w["3. Stop word listener<br>hears the stop word, does not go through the LLM<br>freeze within 1 s"]
    w --> l["4. LLM stop tool<br>the assistant calls stop_skill<br>up to 3 s"]

    classDef planned stroke-dasharray: 5 5
    class w,l planned
```

What to notice:

- The slowest path is the smartest one. The fastest path is a switch on a wire. Never make the smart path the only path.
- The stop key sets an event. The skill thread checks that event every 20 ms, so the measured stop time is a few tens of milliseconds.
- A stop counts as a failed trial in the log, with `stopped_by` filled in. Honest numbers include the stops.

## 5. From one trial to the scoreboard

```mermaid
flowchart LR
    run["One run"] --> line["runs.log<br>time, skill, policy, result, duration, who stopped it"]
    run --> row["trial-log.csv<br>one row, append only"]
    row --> gen["scoreboard.py"]
    gen --> md["SCOREBOARD.md<br>generated, never hand edited"]
    fix["A mistake in a row"] -->|"add a correction row"| row
```

What to notice:

- Rows are never edited. A wrong row gets a correction row after it. The history stays honest.
- The scoreboard is a pure function of the CSV. Run the generator twice and you get the same file. Anyone can regenerate it and check a number.
- A score is 20 trials on one day under one written protocol. Fewer trials, mixed days or a changed layout are not a score.
