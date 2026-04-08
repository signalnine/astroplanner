# Observe Mode Design

Automated telescope control for the Seestar S50. Connects via WebSocket, picks the best target, images it for as long as possible.

## CLI Interface

```
python astroplanner.py --observe [--lp-filter on/off/auto]
```

Reuses existing flags: `--min-alt`, `--min-moon-sep`, `--type`.

## Config

New constants at the top of `astroplanner.py`, next to existing lat/lon:

```python
SEESTAR_IP = "192.168.1.x"   # Set to your Seestar's IP (use static DHCP)
SEESTAR_PORT = 4700
```

## Target Selection

1. Run `compute_night_batch` to get all scored targets
2. Filter out targets with less than 1 hour remaining in their window
3. Adjust scores: `adjusted_score = score * min(1.0, remaining_hours / 3.0)`
4. Pick the highest adjusted-score target

Fallback target is the next-best from the same list, re-filtered at switch time.

## LP Filter Auto-Selection

`--lp-filter auto` (default) selects based on object type:

| Filter ON | Filter OFF |
|-----------|------------|
| emission | galaxy |
| SNR | globular |
| planetary | open cluster |
| | reflection |
| | dark |

ON = dual-band (Ha + OIII). OFF = UV/IR cut (clear).

Log the filter choice per target.

## WebSocket Protocol Layer

Self-contained `SeestarConnection` class. JSON messages over WebSocket on port 4700. Protocol derived from seestar_run source.

Commands needed:
- Connect / disconnect
- Goto (RA/Dec)
- Start stacking
- Stop stacking
- Set LP filter position
- Query status (slewing, stacking, idle, error)

Blocking methods that send a command and wait for the response with a timeout. Reader thread dispatches incoming messages to waiting callers. Main loop stays synchronous.

Uses Python stdlib where possible. May need `websockets` or `websocket-client` as a dependency.

## Session Lifecycle

```
1. STARTUP
   - Compute tonight's plan with adjusted scoring
   - Connect to Seestar (fail fast if unreachable)
   - Log session start, target list, dark window

2. PRIMARY TARGET
   - Pick #1 adjusted-score target
   - Set LP filter (auto/on/off based on --lp-filter and object type)
   - Slew to target RA/Dec, wait for confirmation
   - Start stacking
   - Log: target name, filter state, window end time

3. MONITORING LOOP (every 60s)
   - Query telescope status: stacking active? connection alive?
   - Altitude check via astropy (not telescope-reported position)
   - Check for dawn / configured end time
   - If all good: continue. Log status every 10 min.
   - If stacking stopped: retry (transient error path)
   - If target below min alt: proceed to fallback

4. FALLBACK (once)
   - Stop stacking
   - Re-filter target list for still-observable objects
   - If viable target exists: slew, set filter, start stacking, resume loop
   - If nothing viable: log and stop

5. SHUTDOWN
   - Stop stacking
   - Log session summary: targets, stacking time per target, errors
   - Email summary if SMTP configured
```

## Error Handling

### Classification

| Error | Type | Action |
|-------|------|--------|
| Initial connection fails | Permanent | Fail fast, email, exit |
| Connection refused / wrong IP | Permanent | Fail fast, mention SEESTAR_IP in message |
| Slew fails | Permanent | Skip to fallback target |
| Connection drops mid-session | Transient | Retry with backoff |
| Stacking stops unexpectedly | Transient | Query state, retry |
| Unknown telescope error | Permanent | Log error code, email, exit |

### Retry Logic

- Up to 5 retries, exponential backoff: 10s, 20s, 40s, 80s, 160s
- After reconnect: query telescope state before issuing commands
- If still stacking: resume monitoring (don't re-issue commands)
- If idle: re-slew, restart stacking
- After 5 failures: email alert with session summary, exit

### Logging

- Timestamped lines to stdout (cron redirects to log file)
- Status every 10 minutes during normal stacking
- Immediate log on any error or state change
- Session summary on exit (stdout + email)

### Email on Failure

Reuse existing `send_email()`. Subject includes error summary. Body includes target, runtime, and what went wrong.

## Dependencies

- `websocket-client` or `websockets` (new -- for Seestar communication)
- All existing deps unchanged (astropy, tabulate, optionally skyfield)

## Implementation Notes

- The WebSocket protocol details must be extracted from seestar_run source code (https://github.com/smart-underworld/seestar_run). The exact JSON message format, method names, and response structure are not publicly documented by ZWO.
- Firmware updates may change the protocol. The command surface is small (~6 commands) so fixes should be straightforward.
- Altitude checks in the monitor loop use astropy, not telescope telemetry. This keeps decision logic independent of telescope state and consistent with the planner's existing scoring model.
