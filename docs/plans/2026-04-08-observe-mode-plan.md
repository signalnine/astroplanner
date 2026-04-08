# Observe Mode Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use conclave:executing-plans to implement this plan task-by-task.

**Goal:** Add `--observe` mode that connects to a Seestar S50 telescope via TCP, picks the best target for tonight, and images it for as long as possible.

**Architecture:** New `SeestarConnection` class handles TCP protocol (JSON over raw socket, port 4700). New `run_observe()` function orchestrates target selection, slew, stacking, and monitoring. All code added to the existing single-file `astroplanner.py`.

**Tech Stack:** Python stdlib (`socket`, `json`, `threading`), astropy (existing -- used for coordinate precession and altitude checks)

---

### Task 1: Config Constants and CLI Flags

**Files:**
- Modify: `astroplanner.py:42-47` (config section)
- Modify: `astroplanner.py:1387-1440` (argparse section)

**Dependencies:** none

**Step 1: Add telescope config constants**

After the existing `TIMEZONE_NAME` line (~line 46), add:

```python
# Seestar S50 telescope connection
# Set SEESTAR_IP to your telescope's IP. Tip: assign a static DHCP lease
# in your router so this never changes.
SEESTAR_IP = None             # e.g. "192.168.1.100"
SEESTAR_PORT = 4700

# LP filter auto-selection by object type
# True = dual-band (Ha+OIII), False = UV/IR cut (clear)
LP_FILTER_AUTO = {
    "emission": True, "SNR": True, "planetary": True,
    "galaxy": False, "globular": False, "open cluster": False,
    "reflection": False, "dark": False,
}
```

**Step 2: Add CLI arguments**

In the `main()` function's argparse section, add these arguments:

```python
parser.add_argument(
    "--observe", action="store_true",
    help="Connect to Seestar S50 and image the best target tonight. "
         "Requires SEESTAR_IP to be set in config."
)
parser.add_argument(
    "--lp-filter", type=str, default="auto",
    choices=["on", "off", "auto"],
    help="LP filter mode for --observe (default: auto, selects by object type)"
)
```

**Step 3: Add observe mode dispatch in main()**

After the `args.week` block in `main()`, add:

```python
if args.observe:
    if SEESTAR_IP is None:
        print("Error: Set SEESTAR_IP in astroplanner.py config section.")
        sys.exit(1)
    run_observe(location, start_date, args.min_alt, args.min_moon_sep,
                args.type, args.lp_filter)
    return
```

**Step 4: Test**

Run: `python astroplanner.py --help`
Expected: `--observe` and `--lp-filter` appear in help output.

Run: `python astroplanner.py --observe`
Expected: Error message about SEESTAR_IP not being set.

**Step 5: Commit**

```bash
git add astroplanner.py
git commit -m "Add --observe and --lp-filter CLI flags and config constants"
```

---

### Task 2: SeestarConnection Class -- TCP Transport

**Files:**
- Modify: `astroplanner.py` (add class after the ISS transit section, before weather section)

**Dependencies:** Task 1

**Step 1: Add the TCP transport class**

This class handles: TCP connection, JSON message framing, reader thread, heartbeat, and message dispatch. Place it after the `print_iss_transits` function.

```python
import json as _json
import socket
import threading
import time as _time

class SeestarConnection:
    """Low-level TCP connection to a Seestar S50 telescope (port 4700)."""

    def __init__(self, ip, port=4700, timeout=10):
        self.ip = ip
        self.port = port
        self.timeout = timeout
        self._sock = None
        self._msg_id = 1000
        self._lock = threading.Lock()
        self._resp_lock = threading.Lock()
        self._responses = {}  # id -> threading.Event, result
        self._events = []     # async events from telescope
        self._event_lock = threading.Lock()
        self._reader_thread = None
        self._connected = False
        self._recv_buf = b""

    def connect(self):
        """Connect to the telescope. Sends UDP discovery first."""
        # Stop any existing connection/threads first
        if self._connected:
            self.disconnect()

        # UDP discovery broadcast (guest mode)
        try:
            udp = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            udp.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
            udp.settimeout(2)
            msg = _json.dumps({"id": 1, "method": "scan_iscope", "params": ""})
            udp.sendto(msg.encode() + b"\r\n", (self.ip, 4720))
            udp.close()
        except Exception:
            pass  # non-fatal -- direct TCP may still work

        _time.sleep(0.5)

        self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._sock.settimeout(self.timeout)
        self._sock.connect((self.ip, self.port))
        self._connected = True
        self._recv_buf = b""

        # Start reader thread
        self._reader_thread = threading.Thread(target=self._reader_loop, daemon=True)
        self._reader_thread.start()

    def disconnect(self):
        """Close the connection."""
        self._connected = False
        if self._sock:
            try:
                self._sock.close()
            except Exception:
                pass
            self._sock = None

    def send(self, method, params=None, timeout=30):
        """Send a command and wait for the response. Returns the response dict."""
        with self._lock:
            self._msg_id += 1
            msg_id = self._msg_id

        msg = {"id": msg_id, "method": method}
        if params is not None:
            msg["params"] = params

        event = threading.Event()
        with self._resp_lock:
            self._responses[msg_id] = {"event": event, "result": None}

        raw = _json.dumps(msg) + "\r\n"
        self._sock.sendall(raw.encode())

        if event.wait(timeout):
            with self._resp_lock:
                resp = self._responses.pop(msg_id, {})
            return resp.get("result")
        else:
            with self._resp_lock:
                self._responses.pop(msg_id, None)
            raise TimeoutError(f"No response to {method} (id={msg_id}) within {timeout}s")

    def send_no_wait(self, method, params=None):
        """Send a command without waiting for a response."""
        with self._lock:
            self._msg_id += 1
            msg_id = self._msg_id

        msg = {"id": msg_id, "method": method}
        if params is not None:
            msg["params"] = params

        raw = _json.dumps(msg) + "\r\n"
        self._sock.sendall(raw.encode())
        return msg_id

    def wait_for_event(self, event_name, states=("complete", "fail"), timeout=300):
        """Wait for an async event with the given name to reach a terminal state."""
        deadline = _time.time() + timeout
        while _time.time() < deadline:
            with self._event_lock:
                for i, ev in enumerate(self._events):
                    if ev.get("Event") == event_name and ev.get("state") in states:
                        self._events.pop(i)
                        return ev
            _time.sleep(0.5)
        raise TimeoutError(f"Event {event_name} not received within {timeout}s")

    def drain_events(self, event_name=None):
        """Remove and return all pending events, optionally filtered by name."""
        with self._event_lock:
            if event_name:
                matched = [e for e in self._events if e.get("Event") == event_name]
                self._events = [e for e in self._events if e.get("Event") != event_name]
            else:
                matched = list(self._events)
                self._events.clear()
        return matched

    @property
    def connected(self):
        return self._connected

    def _reader_loop(self):
        """Background thread: read TCP stream, parse JSON messages, dispatch."""
        while self._connected:
            try:
                data = self._sock.recv(65536)
                if not data:
                    self._connected = False
                    break
                self._recv_buf += data

                while b"\r\n" in self._recv_buf:
                    line, self._recv_buf = self._recv_buf.split(b"\r\n", 1)
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        msg = _json.loads(line.decode("utf-8", errors="replace"))
                    except (_json.JSONDecodeError, UnicodeDecodeError):
                        continue

                    # Dispatch: command response (has id) or async event (has Event)
                    if "id" in msg:
                        with self._resp_lock:
                            if msg["id"] in self._responses:
                                entry = self._responses[msg["id"]]
                                entry["result"] = msg
                                entry["event"].set()
                    if "Event" in msg:
                        with self._event_lock:
                            self._events.append(msg)

            except socket.timeout:
                continue
            except OSError:
                self._connected = False
                break
```

**Step 2: Test manually**

This can't be unit-tested without a real telescope, but verify syntax:

Run: `python -c "import astroplanner; print('SeestarConnection' in dir(astroplanner))"`
Expected: `True`

**Step 3: Commit**

```bash
git add astroplanner.py
git commit -m "Add SeestarConnection class for TCP communication"
```

---

### Task 3: High-Level Telescope Commands

**Files:**
- Modify: `astroplanner.py` (add methods or helper class after SeestarConnection)

**Dependencies:** Task 2

**Step 1: Add the Seestar control helper class**

This wraps `SeestarConnection` with astronomy-aware methods. Place it right after `SeestarConnection`.

```python
class SeestarTelescope:
    """High-level Seestar S50 control: goto, stack, filter, status."""

    def __init__(self, ip, port=4700):
        self.conn = SeestarConnection(ip, port)
        self._heartbeat_thread = None
        self._stop_heartbeat = threading.Event()

    def connect(self):
        self.conn.connect()
        # Start heartbeat (scope_get_equ_coord every 5s)
        self._stop_heartbeat.clear()
        self._heartbeat_thread = threading.Thread(target=self._heartbeat, daemon=True)
        self._heartbeat_thread.start()

    def disconnect(self):
        self._stop_heartbeat.set()
        if self._heartbeat_thread:
            self._heartbeat_thread.join(timeout=10)
            self._heartbeat_thread = None
        try:
            self.conn.send("iscope_stop_view", timeout=5)
        except Exception:
            pass
        self.conn.disconnect()

    def goto(self, ra_j2000_hours, dec_j2000_deg, target_name, lp_filter=False):
        """
        Slew to target with plate-solving.
        RA/Dec are J2000; converted to JNow internally.
        Returns True on success, False on failure.
        """
        # Convert J2000 -> JNow
        from astropy.coordinates import FK5
        from astropy.time import Time as AstroTime
        coord = SkyCoord(ra=ra_j2000_hours * u.hourangle, dec=dec_j2000_deg * u.deg, frame="icrs")
        now = AstroTime.now()
        jnow = coord.transform_to(FK5(equinox=now))
        ra_jnow = jnow.ra.hour
        dec_jnow = jnow.dec.deg

        # Drain any old AutoGoto events
        self.conn.drain_events("AutoGoto")

        self.conn.send("iscope_start_view", {
            "mode": "star",
            "target_ra_dec": [ra_jnow, dec_jnow],
            "target_name": target_name,
            "lp_filter": lp_filter,
        }, timeout=10)

        # Wait for goto to complete (up to 5 minutes)
        ev = self.conn.wait_for_event("AutoGoto", timeout=300)
        if ev.get("state") == "complete":
            _time.sleep(3)  # settling time before stacking
            return True
        return False

    def start_stacking(self):
        """Start live stacking. Returns True on success."""
        resp = self.conn.send("iscope_start_stack", {"restart": True}, timeout=10)
        return resp is not None and resp.get("code", -1) == 0

    def stop_stacking(self):
        """Stop current stacking session."""
        try:
            self.conn.send("iscope_stop_view", {"stage": "Stack"}, timeout=10)
        except Exception:
            pass

    def set_lp_filter(self, enabled):
        """Set LP filter. True = dual-band ON, False = clear/UV-IR cut."""
        self.conn.send("set_setting", {"stack_lenhance": enabled}, timeout=10)
        _time.sleep(2)  # wait for filter wheel

    def get_position(self):
        """Get current RA/Dec (JNow). Returns (ra_hours, dec_deg) or None."""
        resp = self.conn.send("scope_get_equ_coord", timeout=5)
        if resp and "result" in resp:
            return resp["result"].get("ra"), resp["result"].get("dec")
        return None

    def is_connected(self):
        return self.conn.connected

    def _heartbeat(self):
        """Send heartbeat every 5 seconds to keep connection alive."""
        while not self._stop_heartbeat.wait(5):
            if not self.conn.connected:
                break
            try:
                self.conn.send_no_wait("scope_get_equ_coord")
            except Exception:
                break
```

**Step 2: Test syntax**

Run: `python -c "import astroplanner; print('SeestarTelescope' in dir(astroplanner))"`
Expected: `True`

**Step 3: Commit**

```bash
git add astroplanner.py
git commit -m "Add SeestarTelescope high-level control class"
```

---

### Task 4: Observe Target Selection

**Files:**
- Modify: `astroplanner.py` (add function after SeestarTelescope class)

**Dependencies:** Task 3

**Step 1: Add the target selection function**

```python
def select_observe_targets(location, start_date, min_alt, min_moon_sep, type_filter=None):
    """
    Select targets for observe mode, ranked by adjusted score.
    Filters out targets with < 1 hour remaining and penalizes short windows.
    Returns sorted list of result dicts with 'adjusted_score' added.
    """
    now_utc = datetime.now(timezone.utc)
    date_utc = datetime(start_date.year, start_date.month, start_date.day,
                        tzinfo=timezone.utc)

    dark_start, dark_end = find_darkness_window(location, date_utc, TIMEZONE_OFFSET)
    if dark_start is None:
        return [], None, None

    targets = parse_catalog_coords(DSO_CATALOG)
    results = compute_night_batch(
        targets, DSO_CATALOG, location, dark_start, dark_end,
        min_alt, min_moon_sep, type_filter=type_filter,
    )

    # Filter and adjust scores based on remaining observable time
    now_time = Time(now_utc.isoformat(), scale="utc")
    filtered = []
    for r in results:
        # Hours remaining from now (or from window start if it hasn't started)
        effective_start = max(r["window_start"], now_time)
        remaining = (r["window_end"] - effective_start).to(u.hour).value
        if remaining < 1.0:
            continue
        r["remaining_hours"] = remaining
        r["adjusted_score"] = r["score"] * min(1.0, remaining / 3.0)
        filtered.append(r)

    filtered.sort(key=lambda r: r["adjusted_score"], reverse=True)
    return filtered, dark_start, dark_end
```

**Step 2: Test**

Run: `python -c "
from astroplanner import *
from astropy.coordinates import EarthLocation
import astropy.units as u
from datetime import datetime, timezone, timedelta
loc = EarthLocation(lat=LATITUDE*u.deg, lon=LONGITUDE*u.deg, height=ELEVATION*u.m)
now = datetime.now(timezone.utc) + timedelta(hours=TIMEZONE_OFFSET)
targets, ds, de = select_observe_targets(loc, now.date(), 35.0, 30.0)
print(f'{len(targets)} targets, top: {targets[0][\"name\"] if targets else \"none\"} adj={targets[0][\"adjusted_score\"]:.1f}' if targets else 'no targets')
"`
Expected: prints target count and top target name with adjusted score.

**Step 3: Commit**

```bash
git add astroplanner.py
git commit -m "Add observe target selection with remaining-time adjustment"
```

---

### Task 5: Observe Session Logging

**Files:**
- Modify: `astroplanner.py` (add logging helper)

**Dependencies:** none

**Step 1: Add timestamped logging function**

Place near the top utility functions (after `utc_to_local_date`):

```python
def observe_log(msg):
    """Print a timestamped log line for observe mode."""
    ts = datetime.now(timezone(timedelta(hours=TIMEZONE_OFFSET))).strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{ts}] {msg}", flush=True)
```

**Step 2: Commit**

```bash
git add astroplanner.py
git commit -m "Add observe_log timestamped logging helper"
```

---

### Task 6: Main Observe Loop (run_observe)

**Files:**
- Modify: `astroplanner.py` (add `run_observe` function)

**Dependencies:** Tasks 1-5

**Step 1: Add the main observe function**

Place after `select_observe_targets`. This is the core session lifecycle.

```python
def run_observe(location, start_date, min_alt, min_moon_sep, type_filter, lp_filter_mode):
    """
    Automated observe session: connect to Seestar, pick best target,
    image it for as long as possible with one fallback.
    """
    observe_log("Starting observe session")

    # 1. Select targets
    candidates, dark_start, dark_end = select_observe_targets(
        location, start_date, min_alt, min_moon_sep, type_filter
    )
    if not candidates:
        observe_log("No observable targets tonight.")
        return

    observe_log(f"Dark window: {utc_to_local(dark_start, TIMEZONE_OFFSET)}-"
                f"{utc_to_local(dark_end, TIMEZONE_OFFSET)} {TIMEZONE_NAME}")
    observe_log(f"Top candidates: " +
                ", ".join(f"{r['name']}({r['adjusted_score']:.0f})" for r in candidates[:5]))

    # 2. Connect to telescope
    observe_log(f"Connecting to Seestar at {SEESTAR_IP}:{SEESTAR_PORT}...")
    scope = SeestarTelescope(SEESTAR_IP, SEESTAR_PORT)
    try:
        scope.connect()
    except Exception as e:
        observe_log(f"FATAL: Cannot connect to telescope -- {e}")
        observe_log(f"Check SEESTAR_IP setting (currently: {SEESTAR_IP})")
        _send_observe_failure_email("Connection failed", str(e), [])
        return

    observe_log("Connected to Seestar S50")
    session_log = []  # list of (target_name, start_time, end_time, status)
    fallback_used = False

    try:
        target_idx = 0
        while target_idx < len(candidates) and (not fallback_used or target_idx <= 1):
            target = candidates[target_idx]
            success = _observe_target(scope, target, dark_end, min_alt,
                                      lp_filter_mode, session_log)
            if success == "done":
                # Clean exit (dawn or end of window)
                break
            elif success == "target_set":
                # Target went below min alt -- try fallback
                if not fallback_used:
                    observe_log("Primary target set. Attempting fallback...")
                    fallback_used = True
                    # Re-filter candidates for still-observable targets
                    now_time = Time(datetime.now(timezone.utc).isoformat(), scale="utc")
                    remaining_candidates = [
                        r for r in candidates[target_idx + 1:]
                        if (r["window_end"] - now_time).to(u.hour).value >= 1.0
                    ]
                    if remaining_candidates:
                        candidates = remaining_candidates
                        target_idx = 0
                        continue
                    else:
                        observe_log("No viable fallback targets remaining.")
                        break
                else:
                    break
            elif success == "error":
                # Unrecoverable error
                break
            target_idx += 1
    finally:
        observe_log("Stopping telescope...")
        scope.disconnect()
        _print_session_summary(session_log)


def _observe_target(scope, target, dark_end, min_alt, lp_filter_mode, session_log):
    """
    Observe a single target. Returns:
      "done" -- dark window ended or should stop
      "target_set" -- target below min altitude
      "error" -- unrecoverable error
    """
    name = target["name"]
    common = target["common"]
    obj_type = target["type"]

    # Determine LP filter setting
    if lp_filter_mode == "on":
        use_lp = True
    elif lp_filter_mode == "off":
        use_lp = False
    else:
        use_lp = LP_FILTER_AUTO.get(obj_type, False)

    lp_str = "ON" if use_lp else "OFF"
    observe_log(f"Target: {name} ({common}) -- {obj_type}, LP filter {lp_str}")
    observe_log(f"Window: until {utc_to_local(target['window_end'], TIMEZONE_OFFSET)} "
                f"{TIMEZONE_NAME} ({target['remaining_hours']:.1f}h remaining)")

    # Set LP filter
    try:
        scope.set_lp_filter(use_lp)
    except Exception as e:
        observe_log(f"Warning: LP filter set failed -- {e}")

    # Get J2000 RA/Dec from the pre-parsed target data
    # peak_time's SkyCoord was already computed by compute_night_batch;
    # we just need the catalog coordinates for the goto command
    cat_entry = next(c for c in DSO_CATALOG if c[0] == name)
    coord = SkyCoord(ra=cat_entry[2], dec=cat_entry[3])
    ra_hours = coord.ra.hour
    dec_deg = coord.dec.deg

    # Goto
    observe_log(f"Slewing to {name}...")
    start_time = datetime.now(timezone.utc)
    retries = 0
    goto_success = False

    while retries < 3:
        try:
            goto_success = scope.goto(ra_hours, dec_deg, name, lp_filter=use_lp)
            break
        except Exception as e:
            retries += 1
            observe_log(f"Goto attempt {retries} failed: {e}")
            if retries < 3:
                _time.sleep(10)

    if not goto_success:
        observe_log(f"FAILED: Could not slew to {name}")
        session_log.append((name, start_time, datetime.now(timezone.utc), "goto_failed"))
        return "target_set"  # try fallback

    # Start stacking
    observe_log(f"Starting stacking on {name}...")
    if not scope.start_stacking():
        observe_log(f"FAILED: Could not start stacking on {name}")
        session_log.append((name, start_time, datetime.now(timezone.utc), "stack_failed"))
        return "target_set"

    observe_log(f"Stacking {name}. Monitoring...")

    # Monitor loop
    last_status_log = _time.time()
    stack_start = _time.time()
    retry_count = 0
    max_retries = 5
    backoff_delays = [10, 20, 40, 80, 160]

    while True:
        _time.sleep(60)

        # Check dark window
        now_utc = Time(datetime.now(timezone.utc).isoformat(), scale="utc")
        if now_utc >= dark_end:
            elapsed = (_time.time() - stack_start) / 3600
            observe_log(f"Dark window ended. Stacked {name} for {elapsed:.1f}h")
            scope.stop_stacking()
            session_log.append((name, start_time, datetime.now(timezone.utc), "complete"))
            return "done"

        # Check target altitude
        altaz_frame = AltAz(obstime=now_utc, location=EarthLocation(
            lat=LATITUDE * u.deg, lon=LONGITUDE * u.deg, height=ELEVATION * u.m
        ))
        target_coord = SkyCoord(ra=ra_hours * u.hourangle, dec=dec_deg * u.deg)
        alt = target_coord.transform_to(altaz_frame).alt.deg
        if alt < min_alt:
            elapsed = (_time.time() - stack_start) / 3600
            observe_log(f"{name} below {min_alt}deg (alt={alt:.1f}deg). "
                        f"Stacked for {elapsed:.1f}h")
            scope.stop_stacking()
            session_log.append((name, start_time, datetime.now(timezone.utc), "target_set"))
            return "target_set"

        # Check connection
        if not scope.is_connected():
            observe_log("Connection lost. Attempting reconnect...")
            reconnected = False
            for i in range(max_retries):
                delay = backoff_delays[min(i, len(backoff_delays) - 1)]
                observe_log(f"Retry {i+1}/{max_retries} in {delay}s...")
                _time.sleep(delay)
                try:
                    scope.connect()
                    # Check telescope state after reconnect
                    pos = scope.get_position()
                    if pos:
                        observe_log(f"Reconnected. Position: RA={pos[0]:.4f} Dec={pos[1]:.4f}")
                        # Check if telescope is still on-target and stacking
                        # (TCP drop doesn't necessarily stop the telescope)
                        ra_diff = abs(pos[0] - ra_hours) * 15  # rough arcmin
                        dec_diff = abs(pos[1] - dec_deg) * 60
                        if ra_diff < 5 and dec_diff < 5:
                            observe_log("Telescope still on target. Resuming monitor.")
                            reconnected = True
                            break
                        # Off target -- re-slew and restart
                        observe_log(f"Off target. Re-acquiring {name}...")
                        if scope.goto(ra_hours, dec_deg, name, lp_filter=use_lp):
                            if scope.start_stacking():
                                observe_log("Stacking resumed.")
                                reconnected = True
                                break
                except Exception as e:
                    observe_log(f"Reconnect attempt failed: {e}")

            if not reconnected:
                observe_log("FATAL: Could not reconnect after 5 attempts.")
                session_log.append((name, start_time, datetime.now(timezone.utc), "connection_lost"))
                _send_observe_failure_email("Connection lost",
                    f"Lost connection while imaging {name}. 5 reconnect attempts failed.",
                    session_log)
                return "error"

        # Periodic status log (every 10 min)
        if _time.time() - last_status_log >= 600:
            elapsed = (_time.time() - stack_start) / 60
            observe_log(f"Stacking {name}: {elapsed:.0f} min elapsed, alt={alt:.1f}deg")
            last_status_log = _time.time()


def _send_observe_failure_email(subject_detail, body_detail, session_log):
    """Send an email alert on observe failure. Falls back to stdout if no email config."""
    summary_lines = [f"Observe session failure: {subject_detail}", "", body_detail, ""]
    if session_log:
        summary_lines.append("Session log:")
        for name, start, end, status in session_log:
            duration = (end - start).total_seconds() / 3600
            summary_lines.append(f"  {name}: {duration:.1f}h -- {status}")
    body = "\n".join(summary_lines)
    subject = f"Seestar: {subject_detail}"
    if not send_email(subject, body):
        observe_log(body)


def _print_session_summary(session_log):
    """Print observe session summary."""
    if not session_log:
        observe_log("Session complete. No targets were imaged.")
        return

    observe_log("=" * 60)
    observe_log("SESSION SUMMARY")
    total_hours = 0
    for name, start, end, status in session_log:
        duration = (end - start).total_seconds() / 3600
        total_hours += duration
        status_str = {"complete": "ok", "target_set": "target set",
                      "goto_failed": "goto failed", "stack_failed": "stack failed",
                      "connection_lost": "connection lost"}.get(status, status)
        observe_log(f"  {name}: {duration:.1f}h -- {status_str}")
    observe_log(f"Total imaging time: {total_hours:.1f}h")
    observe_log("=" * 60)

    # Email summary
    lines = ["Seestar observe session complete.", ""]
    for name, start, end, status in session_log:
        duration = (end - start).total_seconds() / 3600
        lines.append(f"{name}: {duration:.1f}h ({status})")
    lines.append(f"\nTotal: {total_hours:.1f}h")
    send_email(f"Seestar: session complete -- {total_hours:.1f}h imaging", "\n".join(lines))
```

**Step 2: Test syntax**

Run: `python -c "from astroplanner import run_observe; print('ok')"`
Expected: `ok`

**Step 3: Commit**

```bash
git add astroplanner.py
git commit -m "Add run_observe main loop with fallback and error recovery"
```

---

### Task 7: Integration Test on Haight

**Files:** none (testing only)

**Dependencies:** Tasks 1-6

**Step 1: Push to GitHub and pull on haight**

```bash
git push
ssh gabe@haight "cd ~/astroplanner && git pull"
```

**Step 2: Test --help**

```bash
ssh gabe@haight "/home/gabe/astroplanner/.venv/bin/python /home/gabe/astroplanner/astroplanner.py --help"
```
Expected: `--observe` and `--lp-filter` in help output.

**Step 3: Test without SEESTAR_IP**

```bash
ssh gabe@haight "/home/gabe/astroplanner/.venv/bin/python /home/gabe/astroplanner/astroplanner.py --observe"
```
Expected: Error about SEESTAR_IP not being set.

**Step 4: Test with a bogus IP (connection failure path)**

Temporarily set SEESTAR_IP to a non-routable address and run `--observe`. Verify it fails fast with a clear error message and (if email is configured) sends a failure alert.

**Step 5: Test with the real telescope**

Once the user provides the Seestar's IP:
1. Set `SEESTAR_IP` in config
2. Run: `python astroplanner.py --observe`
3. Verify: connects, picks target, slews, starts stacking, logs status every 10 min
4. Let it run for 15-20 minutes to confirm monitoring loop works
5. Check that LP filter was set correctly for the chosen target type

**Step 6: Commit config with real IP (if desired)**

```bash
git add astroplanner.py
git commit -m "Set SEESTAR_IP for home network"
```
