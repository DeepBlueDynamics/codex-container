# Agent Execution Patterns: Complete Taxonomy

## Core Execution Modes

### 1. Interactive Mode
**Definition**: Agent responds to user input in real-time, immediate feedback loop

**Variants**:
- **Synchronous Interactive**: Blocking wait for response before returning control
- **Asynchronous Interactive**: Non-blocking, returns immediately, response comes via callback/stream
- **Streaming Interactive**: Partial responses yielded incrementally during computation
- **Turn-based Interactive**: Single-turn exchanges with explicit boundaries

**State handling**: Typically in-memory, session-scoped

---

### 2. Session-Resuming Mode
**Definition**: Agent loads previous execution state and continues from checkpoint

**Variants**:
- **Stateless Resumption**: Load only parameter/context, recompute from scratch
- **Stateful Resumption**: Load full memory, state tree, execution context
- **Partial Resumption**: Load specific subtasks/branches, skip others
- **Branching Resumption**: Resume from checkpoint into alternative execution paths

**State handling**: Persisted (disk, database, blob storage)

**Checkpointing strategies**:
- Full serialization (all memory)
- Differential checkpoints (changes only)
- Checkpoint trees (fork points for exploration)

---

### 3. Scheduled/Timer Mode
**Definition**: Agent triggered by external timer, cron, or event scheduler

**Variants**:
- **Fixed-interval Scheduled**: Runs every N seconds/minutes/hours (cron-like)
- **Event-triggered**: Runs when external signal fires (message queue, webhook, file created)
- **Debounced Scheduled**: Batches triggers within window, runs once
- **Throttled Scheduled**: Limits execution frequency regardless of trigger count
- **Backpressure-aware**: Runs only if previous execution complete

**State handling**: Usually persistent (needs to resume where it left off)

---

### 4. Daemon/Long-Running Mode
**Definition**: Agent runs continuously, processing streams, watching queues

**Variants**:
- **Queue Watcher**: Continuously polls/listens to message queue
- **Stream Processor**: Handles streaming data (socket, HTTP stream, Kafka)
- **Loop-based Daemon**: Infinite loop with wait/process/persist cycle
- **Reactive Daemon**: Responds to file system, network, or system events

**State handling**: Persistent + in-memory buffer

---

### 5. Batch Mode
**Definition**: Agent processes bulk inputs as single execution

**Variants**:
- **Sequential Batch**: Process items one after another
- **Parallel Batch**: Process items in parallel batches
- **Windowed Batch**: Group items by time/size window, process each window
- **Incremental Batch**: Process, persist after each item

**State handling**: Accumulated across batch

---

### 6. Hierarchical/Nested Mode
**Definition**: Agent spawns sub-agents, orchestrates their execution

**Variants**:
- **Synchronous Orchestration**: Wait for all children, aggregate results
- **Asynchronous Orchestration**: Fire-and-forget children, collect results later
- **Recursive Delegation**: Agent delegates to copy of itself with constrained scope
- **Pipeline Mode**: Chain agents sequentially (output of one = input to next)

**State handling**: Tree-structured state, parent-child coordination

---

## State & Session Patterns

### State Persistence Strategies

| Pattern | When Used | Trade-off |
|---------|-----------|-----------|
| **Ephemeral (None)** | Single interactive session | Speed vs durability |
| **Memory-only** | Fast single-host execution | Crashes lose state |
| **Disk (Local)** | Development, single machine | Not distributed |
| **Database** | Production, distributed | Latency, complexity |
| **Distributed Cache** (Redis) | Multi-machine, fast resumption | Eventual consistency |
| **Event Sourcing** | Full audit trail needed | Complexity, storage |
| **Immutable Snapshots** | Branching/exploration | Storage cost |

### Session Lifecycle

```
Creation → Active → Pause/Checkpoint → Resume → Completion
                ↓
            Termination
                ↓
            Cleanup/Archive
```

**Variants**:
- **Single-use session**: Create, run, destroy
- **Reusable session**: Keep alive across multiple runs
- **Session pool**: Multiple concurrent sessions, load-balanced
- **Session hierarchy**: Parent session manages child sessions

---

## Timing & Event Patterns

### Trigger Types

1. **Time-based**
   - Absolute: "Run at 2024-11-20 14:30:00"
   - Relative: "Run in 5 minutes"
   - Recurring: "Every 30 minutes", "Every Monday at 9am"
   - Rate-limited: "Max once per 10 seconds"

2. **Event-based**
   - External event: Webhook, API call, message arrival
   - Internal event: Condition met, threshold crossed, state change
   - Signal-based: Unix signals, interrupts
   - Reactive: File system watcher, database trigger

3. **Data-driven**
   - Condition trigger: "When queue length > 100"
   - Change trigger: "When config file modified"
   - Dependency trigger: "When upstream agent completes"

4. **Manual**
   - User-initiated: Button click, CLI command
   - Explicit call: Direct function invocation

---

## Combinatorial Patterns

### 2-Factor Combinations

**Mode × Session Type**:
| | Fresh | Resuming | Forked |
|---|---|---|---|
| **Interactive** | New chatbot | Resume conversation | Branch from checkpoint |
| **Scheduled** | Run from scratch | Continue job | Explore alternative path |
| **Daemon** | Start new worker | Recover crashed worker | Parallel variant |
| **Batch** | Process new batch | Retry failed batch | Process variant subset |

**Mode × Timing**:
| | Immediate | Delayed | Recurring |
|---|---|---|---|
| **Interactive** | Stream response | Schedule for later | Repeating prompt? |
| **Daemon** | Start now | Start at time | Restart every interval |
| **Batch** | Run now | Queue run | Run every day |

### 3-Factor Combinations

**Mode × Session × Concurrency**:

Example: *Scheduled + Resuming + Concurrent*
- Multiple instances of same agent resume from different checkpoints
- All run on timer trigger
- Share coordinator lock/queue to avoid conflicts

Example: *Daemon + Branching + Hierarchical*
- Long-running parent daemon
- Spawns child agents (branches) for specific tasks
- Each child can fork further
- All share parent's session state

---

## Advanced Patterns

### 1. Multi-Mode Agent (Mode Switching)
**Definition**: Single agent that changes execution mode based on context

```
Interactive → (User goes offline) → Scheduled → (Signal arrives) → Event-Driven
                                                                      ↓
                                                                  Batch Processing
```

**Use case**: Chatbot that auto-continues while user away, then resumes interactively

---

### 2. Canary-to-Production Pattern
```
Canary (Scheduled, low-traffic) 
    ↓ (validates)
Staging (Scheduled, mid-traffic)
    ↓ (validates)
Production (Daemon, full-traffic)
```

**State**: Copied forward through each stage

---

### 3. Exploratory Forking Pattern
```
Main Session (Scheduled)
    ├─ Fork A (Resumable checkpoint)
    │   └─ Explore strategy A (batch mode)
    ├─ Fork B (Resumable checkpoint)
    │   └─ Explore strategy B (batch mode)
    ├─ Fork C (Resumable checkpoint)
    │   └─ Explore strategy C (batch mode)
    └─ (Merge results, update main)
```

**State**: Tree structure with independent branches

---

### 4. Backpressure Cascade Pattern
```
Source (Stream) 
    → Buffer (Daemon watching queue)
        → Slow consumer (Batch, respects backpressure)
            → Downstream (Scheduled, pulls batches)
```

**Coordination**: Each layer waits for capacity before accepting

---

### 5. State Machine Pattern
**Definition**: Agent states that trigger mode transitions

```
[IDLE] --trigger--> [RUNNING] --complete--> [IDLE]
                      ↓
                   [PAUSED] --resume--> [RUNNING]
                      ↓
                   [CHECKPOINTED] --fork--> [RUNNING] (variant)
```

---

## Implementation Considerations

### For Fresh Interactive:
- Minimal initialization
- Stream responses immediately
- Hold state in memory
- No recovery needed

### For Session Resumption:
- Load serialized state
- Validate state integrity
- Resume from last checkpoint
- Decide: continue or branch?

### For Scheduled:
- Register with scheduler (cron, APScheduler, etc.)
- Load previous session on trigger
- Handle missed runs (backfill, skip, or catch-up)
- Persist results before next run

### For Daemon:
- Initialize once, keep alive
- Implement heartbeat/health check
- Handle graceful shutdown
- Implement circuit breakers for failures

### For Batch:
- Accumulate inputs
- Process in chunks
- Persist checkpoint after each chunk
- Handle partial failures (retry/skip)

### For Hierarchical:
- Manage parent-child coordination
- Aggregate child results
- Implement timeout/cancellation
- Handle cascading failures

---

## State Representation

### Minimal State
```json
{
  "session_id": "uuid",
  "mode": "interactive",
  "last_checkpoint": null,
  "created_at": "timestamp"
}
```

### Full State
```json
{
  "session_id": "uuid",
  "mode": "daemon",
  "state": {
    "memory": {...},
    "execution_tree": {...},
    "registers": {...},
    "call_stack": [...]
  },
  "checkpoints": [
    {"id": "cp1", "timestamp": "...", "state": {...}},
    {"id": "cp2", "timestamp": "...", "state": {...}}
  ],
  "metadata": {
    "parent_session": "uuid or null",
    "child_sessions": ["uuid", "uuid"],
    "mode_history": ["interactive", "scheduled", "daemon"],
    "trigger_source": "event_type",
    "last_error": "exception or null"
  }
}
```

---

## Decision Tree: Which Pattern?

```
1. How triggered?
   ├─ User input → Interactive
   ├─ Timer/Schedule → Scheduled + (Fresh vs Resuming)
   ├─ External event → Event-Driven
   └─ Continuous → Daemon

2. Need persistence?
   ├─ No → Ephemeral (keep in memory)
   └─ Yes → Database/Cache + Checkpointing

3. Parallel execution?
   ├─ No → Single-threaded, sequential
   ├─ Yes, coordinated → Hierarchical
   └─ Yes, independent → Batch + parallel

4. State scope?
   ├─ Single-session → Linear
   ├─ Multiple branches → Tree with forks
   └─ Complex orchestration → DAG/Graph

5. Failure handling?
   ├─ Fail-fast → No checkpointing needed
   ├─ Retry once → Checkpoint before execution
   ├─ Resume exactly → Full state persistence
   └─ Resume approximately → Differential checkpoints
```

---

## Example Concrete Scenarios

### Scenario 1: Chatbot
- **Primary**: Interactive mode
- **Secondary**: Session-resuming (load chat history)
- **Tertiary**: Scheduled (remind user if idle)
- **State**: Database (chat history) + memory (current conversation)

### Scenario 2: Data Pipeline
- **Primary**: Daemon (watches input queue)
- **Secondary**: Batch (processes in chunks)
- **Tertiary**: Scheduled (cleanup, archival)
- **State**: Persistent (which items processed, checkpoints)

### Scenario 3: Testing Harness
- **Primary**: Batch mode (test suite)
- **Secondary**: Forking (each test variant)
- **Tertiary**: Hierarchical (parent coordinates, children run tests)
- **State**: Immutable snapshots for each fork

### Scenario 4: Recommendation Engine
- **Primary**: Scheduled (daily recompute)
- **Secondary**: Interactive (serve current recommendations)
- **Tertiary**: Event-triggered (retrain on signal)
- **State**: Database (model weights) + cache (current results)

### Scenario 5: Monitoring/Alert System
- **Primary**: Daemon (continuously monitor metrics)
- **Secondary**: Event-triggered (fire alert on threshold)
- **Tertiary**: Scheduled (periodic reports)
- **State**: Time-series DB (metrics) + memory (current thresholds)

---

## The Unified Model

All these patterns are variations on:

```
State(t) + Trigger + ExecutionMode → Computation → State(t+1) + Output
```

Where:
- **State(t)**: Current checkpoint/session state
- **Trigger**: When/why execution begins
- **ExecutionMode**: How agent processes (interactive, batch, stream, etc.)
- **Computation**: The actual work
- **State(t+1)**: Updated state after computation
- **Output**: Result to user/system

The key insight: **Every pattern is a different way to parameterize this equation.**

---

## Extending Further

### Future dimensions:
- **Distributed coordination**: Agents across multiple machines
- **Multi-modal reasoning**: Agent switches between thinking modes
- **Adaptive timing**: Agent adjusts trigger frequency based on workload
- **Quantum superposition**: Explore all branches simultaneously (metaphorical?)
- **Meta-agents**: Agents that manage other agents' execution
- **Zero-knowledge sessions**: Resumption without loading full state (cryptographic verification)