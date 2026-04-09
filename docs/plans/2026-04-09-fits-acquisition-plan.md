# FITS Sub-frame Acquisition Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use conclave:executing-plans to implement this plan task-by-task.

**Goal:** Replace the broken Alpaca `startexposure` stacking with a continuous exposure-and-save loop that writes each sub-frame as a FITS file with rich metadata, plus a simple preview PNG.

**Architecture:** The `_observe_target` monitor loop becomes an expose/download/save loop. `SeestarTelescope` gains `expose()` and `download_image()` methods. Each frame is saved immediately as FITS. A running mean preview updates every 50 frames. No alignment, no stacking beyond the preview.

**Tech Stack:** astropy.io.fits (already installed), PIL/Pillow (already installed on haight), numpy (already installed), urllib (stdlib)

---

### Task 1: Add camera methods to SeestarTelescope

**Files:**
- Modify: `astroplanner.py:754-768` (replace `start_stacking`/`stop_stacking`)

**Dependencies:** none

**Step 1: Replace start_stacking and stop_stacking with expose and download_image**

Replace lines 754-768 in `SeestarTelescope` with:

```python
def expose(self, duration=10.0):
    """Start an exposure and wait for it to complete. Returns True on success."""
    resp = self._put("camera", 0, "startexposure",
                     Duration=duration, Light="true")
    if resp.get("ErrorNumber", 0) != 0:
        return False
    # Poll until image is ready (timeout: duration + 30s for readout/download)
    deadline = _time.time() + duration + 30
    while _time.time() < deadline:
        _time.sleep(1)
        try:
            ready = self._get("camera", 0, "imageready")
            if ready.get("Value", False):
                return True
        except Exception:
            pass
    return False

def download_image(self):
    """Download the last exposed image as a numpy array. Returns (array, None) or (None, error)."""
    import urllib.request
    try:
        url = f"{self.base}/api/v1/camera/0/imagearray?ClientID=1&ClientTransactionID={self._txn_id}"
        resp = urllib.request.urlopen(url, timeout=60)
        data = _json.loads(resp.read().decode())
        if data.get("ErrorNumber", 0) != 0:
            return None, data.get("ErrorMessage", "unknown error")
        import numpy as np
        arr = np.array(data["Value"], dtype=np.uint16)
        return arr, None
    except Exception as e:
        return None, str(e)

def abort_exposure(self):
    """Abort current exposure."""
    try:
        self._put("camera", 0, "abortexposure")
    except Exception:
        pass
```

**Step 2: Verify syntax**

Run: `python3 -c "import ast; ast.parse(open('astroplanner.py').read()); print('ok')"`
Expected: `ok`

**Step 3: Commit**

```bash
git add astroplanner.py
git commit -m "Add expose() and download_image() to SeestarTelescope"
```

---

### Task 2: Add --exposure CLI flag

**Files:**
- Modify: `astroplanner.py:1932-1935` (add --exposure argument after --lp-filter)
- Modify: `astroplanner.py:1968` (pass exposure to run_observe)
- Modify: `astroplanner.py:841` (add exposure_time parameter to run_observe)

**Dependencies:** none

**Step 1: Add the --exposure argument**

After the `--target` argument (~line 1935), add:

```python
parser.add_argument(
    "--exposure", type=float, default=10.0,
    help="Exposure time per sub-frame in seconds for --observe (default: 10.0)"
)
```

**Step 2: Update run_observe signature and call site**

Change `run_observe` signature (line 841) to accept `exposure_time=10.0`:

```python
def run_observe(location, start_date, min_alt, min_moon_sep, type_filter,
                lp_filter_mode, target_name=None, exposure_time=10.0):
```

Update the call site (~line 1968) to pass `args.exposure`:

```python
run_observe(location, start_date, args.min_alt, args.min_moon_sep,
            args.type, args.lp_filter, args.target, args.exposure)
```

**Step 3: Add exposure validation in run_observe**

At the top of `run_observe`, after the "Starting observe session" log:

```python
if exposure_time < 1 or exposure_time > 30:
    observe_log(f"WARNING: Exposure {exposure_time}s is outside recommended 1-30s range")
```

**Step 4: Verify syntax**

Run: `python3 -c "import ast; ast.parse(open('astroplanner.py').read()); print('ok')"`
Expected: `ok`

**Step 5: Commit**

```bash
git add astroplanner.py
git commit -m "Add --exposure CLI flag for sub-frame duration"
```

---

### Task 3: Add FITS save helper function

**Files:**
- Modify: `astroplanner.py` (add function after `_print_session_summary`, before the Weather section at line 1125)

**Dependencies:** Task 1

**Step 1: Add _save_fits function**

```python
def _save_fits(image_array, output_dir, target_name, frame_num, ra_hours, dec_deg,
               exposure_time, filter_name, timestamp_utc):
    """Save a single sub-frame as a FITS file with metadata headers."""
    from astropy.io import fits
    import numpy as np

    hdu = fits.PrimaryHDU(image_array.astype(np.uint16))
    h = hdu.header
    h["OBJECT"] = target_name
    h["RA"] = ra_hours * 15.0  # convert hours to degrees
    h["DEC"] = dec_deg
    h["DATE-OBS"] = timestamp_utc.strftime("%Y-%m-%dT%H:%M:%S")
    h["EXPTIME"] = exposure_time
    h["FILTER"] = filter_name
    h["FRAME"] = frame_num
    h["INSTRUME"] = "Seestar S50"
    h["TELESCOP"] = "ZWO Seestar S50"
    h["FOCALLEN"] = 463
    h["APERTURE"] = 50
    h["SITELAT"] = LATITUDE
    h["SITELONG"] = LONGITUDE

    fname = os.path.join(output_dir, f"{target_name}_{frame_num:04d}.fits")
    hdu.writeto(fname, overwrite=True)
    return fname
```

Also add `import os` near the existing mid-file imports (line 670):

```python
import os
```

**Step 2: Add _update_preview function**

```python
def _update_preview(image_array, preview_path, frame_count, running_sum):
    """Update running mean preview PNG. Returns updated running_sum."""
    import numpy as np

    if running_sum is None:
        running_sum = image_array.astype(np.float64)
    else:
        running_sum += image_array.astype(np.float64)

    # Compute mean and stretch for display
    mean = running_sum / frame_count
    # Log stretch
    stretched = np.log1p(mean - mean.min())
    max_val = stretched.max()
    if max_val > 0:
        stretched = (stretched / max_val * 255).astype(np.uint8)
    else:
        stretched = np.zeros_like(mean, dtype=np.uint8)

    from PIL import Image
    img = Image.fromarray(stretched)
    img.save(preview_path)
    return running_sum
```

**Step 3: Verify syntax**

Run: `python3 -c "import ast; ast.parse(open('astroplanner.py').read()); print('ok')"`
Expected: `ok`

**Step 4: Commit**

```bash
git add astroplanner.py
git commit -m "Add FITS save and preview update helper functions"
```

---

### Task 4: Rewrite _observe_target with exposure loop

**Files:**
- Modify: `astroplanner.py:954-1081` (replace entire `_observe_target` function)

**Dependencies:** Task 1, Task 2, Task 3

**Step 1: Rewrite _observe_target**

Replace the entire function with:

```python
def _observe_target(scope, target, location, dark_end, min_alt, lp_filter_mode,
                    session_log, exposure_time=10.0):
    """
    Observe a single target by taking continuous sub-frame exposures.
    Saves each frame as FITS, updates preview every 50 frames.
    Returns:
      "done" -- dark window ended
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

    filter_name = "LP" if use_lp else "IR"
    observe_log(f"Target: {name} ({common}) -- {obj_type}, filter {filter_name}")
    observe_log(f"Window: until {utc_to_local(target['window_end'], TIMEZONE_OFFSET)} "
                f"{TIMEZONE_NAME} ({target['remaining_hours']:.1f}h remaining)")

    # Set LP filter
    try:
        scope.set_lp_filter(use_lp)
    except Exception as e:
        observe_log(f"Warning: LP filter set failed -- {e}")

    # Get J2000 RA/Dec from catalog
    cat_entry = next(c for c in DSO_CATALOG if c[0] == name)
    coord = SkyCoord(ra=cat_entry[2], dec=cat_entry[3])
    ra_hours = coord.ra.hour
    dec_deg = coord.dec.deg

    # Goto
    observe_log(f"Slewing to {name}...")
    start_time = datetime.now(timezone.utc)

    goto_success = False
    for attempt in range(3):
        try:
            goto_success = scope.goto(ra_hours, dec_deg, name, lp_filter=use_lp)
            if goto_success:
                break
        except Exception as e:
            observe_log(f"Goto attempt {attempt + 1} failed: {e}")
            if attempt < 2:
                _time.sleep(10)

    if not goto_success:
        observe_log(f"FAILED: Could not slew to {name}")
        session_log.append((name, start_time, datetime.now(timezone.utc), "goto_failed"))
        return "target_set"

    # Create output directory
    date_str = start_time.strftime("%Y-%m-%d")
    output_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                              "captures", f"{date_str}_{name}")
    os.makedirs(output_dir, exist_ok=True)
    preview_path = os.path.join(output_dir, "preview.png")

    observe_log(f"Saving sub-frames to {output_dir}")
    observe_log(f"Starting {exposure_time}s exposures on {name}...")

    # Exposure loop
    frame_num = 0
    running_sum = None
    last_status_log = _time.time()
    consecutive_failures = 0

    while True:
        # Check dark window
        now_utc = Time(datetime.now(timezone.utc))
        if now_utc >= dark_end:
            observe_log(f"Dark window ended. Captured {frame_num} frames of {name}")
            session_log.append((name, start_time, datetime.now(timezone.utc), "complete"))
            return "done"

        # Check target altitude (every 10 frames to avoid overhead)
        if frame_num % 10 == 0 and frame_num > 0:
            altaz_frame = AltAz(obstime=now_utc, location=location)
            target_coord = SkyCoord(ra=ra_hours * u.hourangle, dec=dec_deg * u.deg)
            alt = target_coord.transform_to(altaz_frame).alt.deg
            if alt < min_alt:
                observe_log(f"{name} below {min_alt}deg (alt={alt:.1f}deg). "
                            f"Captured {frame_num} frames")
                session_log.append((name, start_time, datetime.now(timezone.utc), "target_set"))
                return "target_set"

        # Take exposure
        if not scope.expose(exposure_time):
            consecutive_failures += 1
            observe_log(f"Exposure failed (attempt {consecutive_failures})")
            if consecutive_failures >= 5:
                observe_log(f"FATAL: 5 consecutive exposure failures on {name}")
                session_log.append((name, start_time, datetime.now(timezone.utc), "exposure_failed"))
                _send_observe_email("Exposure failed",
                    f"5 consecutive exposure failures on {name} after {frame_num} frames.",
                    session_log)
                return "error"
            _time.sleep(5)
            continue

        consecutive_failures = 0

        # Download image
        image, err = scope.download_image()
        if image is None:
            observe_log(f"Download failed: {err}")
            continue  # skip this frame, try next exposure

        frame_num += 1
        timestamp = datetime.now(timezone.utc)

        # Save FITS
        _save_fits(image, output_dir, name, frame_num, ra_hours, dec_deg,
                   exposure_time, filter_name, timestamp)

        # Update preview every 50 frames
        if frame_num % 50 == 0 or frame_num == 1:
            running_sum = _update_preview(image, preview_path, frame_num, running_sum)
            observe_log(f"Frame {frame_num} saved. Preview updated.")
        elif running_sum is not None:
            import numpy as np
            running_sum += image.astype(np.float64)

        # Periodic status log (every 10 min)
        if _time.time() - last_status_log >= 600:
            elapsed_min = (_time.time() - (start_time - datetime(1970, 1, 1, tzinfo=timezone.utc)).total_seconds()) / 60
            elapsed_min = (datetime.now(timezone.utc) - start_time).total_seconds() / 60
            observe_log(f"Imaging {name}: {frame_num} frames, {elapsed_min:.0f} min elapsed")
            last_status_log = _time.time()
```

**Step 2: Update the call in run_observe to pass exposure_time**

Change line ~917 from:
```python
result = _observe_target(scope, target, location, dark_end, min_alt,
                         lp_filter_mode, session_log)
```
to:
```python
result = _observe_target(scope, target, location, dark_end, min_alt,
                         lp_filter_mode, session_log, exposure_time)
```

**Step 3: Update run_observe finally block**

Replace `scope.stop_stacking()` with `scope.abort_exposure()`:

```python
finally:
    observe_log("Parking telescope...")
    try:
        scope.abort_exposure()
        scope._put("telescope", 0, "park")
        observe_log("Telescope parked (arm stowed).")
    except Exception as e:
        observe_log(f"Warning: Park failed -- {e}")
    scope.disconnect()
    _print_session_summary(session_log)
```

**Step 4: Verify syntax**

Run: `python3 -c "import ast; ast.parse(open('astroplanner.py').read()); print('ok')"`
Expected: `ok`

**Step 5: Commit**

```bash
git add astroplanner.py
git commit -m "Rewrite observe loop: continuous FITS sub-frame acquisition"
```

---

### Task 5: Update session summary with frame counts

**Files:**
- Modify: `astroplanner.py:1097-1122` (`_print_session_summary`)
- Modify: `astroplanner.py:1083-1094` (`_send_observe_email`)

**Dependencies:** Task 4

**Step 1: Update session_log format**

The session_log tuples now include frame count as a 5th element. Update both functions to handle it.

In `_send_observe_email`, change:
```python
for name, start, end, status in session_log:
```
to:
```python
for entry in session_log:
    name, start, end, status = entry[0], entry[1], entry[2], entry[3]
    frames = entry[4] if len(entry) > 4 else 0
```
And include frame count in the output.

Similarly in `_print_session_summary`.

Also update the session_log.append calls in Task 4 to include frame_num:
```python
session_log.append((name, start_time, datetime.now(timezone.utc), "complete", frame_num))
```

**Step 2: Update --tonight instructions**

Change the setup instructions (~line 2131-2142) to include the auto power-off reminder:

```python
print(f"  To image tonight's top target automatically:")
print(f"    1. In Seestar app: Settings > Auto Power Off > Never (first time only)")
print(f"    2. Power on the Seestar and let it connect to WiFi")
print(f"    3. Open the phone app, open the arm, then close the app")
print(f"    4. Run: python astroplanner.py --observe")
print(f"")
print(f"  The telescope will slew to {top['name']} ({top['common']}),")
print(f"  set the {lp_str} filter, and capture {exposure_time}s sub-frames")
print(f"  for {top['hours_above']:.1f}h. Stack the FITS files in Siril/DSS.")
print(f"  At dawn it will park the telescope and email a summary.")
```

**Step 3: Verify syntax**

Run: `python3 -c "import ast; ast.parse(open('astroplanner.py').read()); print('ok')"`
Expected: `ok`

**Step 4: Commit**

```bash
git add astroplanner.py
git commit -m "Update session summary with frame counts and setup instructions"
```

---

### Task 6: Deploy and test on haight

**Files:** none (deployment)

**Dependencies:** Task 5

**Step 1: Push and pull**

```bash
git push
ssh gabe@haight "cd ~/astroplanner && git pull"
```

**Step 2: Verify imports**

```bash
ssh gabe@haight '/home/gabe/astroplanner/.venv/bin/python -c "
from astroplanner import SeestarTelescope, _save_fits, _update_preview
print(\"imports ok\")"'
```
Expected: `imports ok`

**Step 3: Test FITS save with dummy data**

```bash
ssh gabe@haight '/home/gabe/astroplanner/.venv/bin/python -c "
import sys, os, numpy as np
sys.path.insert(0, \"/home/gabe/astroplanner\")
from astroplanner import _save_fits
from datetime import datetime, timezone

os.makedirs(\"/tmp/fits_test\", exist_ok=True)
img = np.random.randint(500, 30000, (1080, 1920), dtype=np.uint16)
f = _save_fits(img, \"/tmp/fits_test\", \"M94\", 1, 12.848, 41.12, 10.0, \"IR\",
               datetime.now(timezone.utc))
print(f\"Saved: {f}\")

from astropy.io import fits
h = fits.getheader(f)
print(f\"OBJECT={h[\"OBJECT\"]}, EXPTIME={h[\"EXPTIME\"]}, FILTER={h[\"FILTER\"]}\")
print(f\"RA={h[\"RA\"]}, DEC={h[\"DEC\"]}, FRAME={h[\"FRAME\"]}\")
"'
```
Expected: Header values match what was passed in.

**Step 4: Test preview generation**

```bash
ssh gabe@haight '/home/gabe/astroplanner/.venv/bin/python -c "
import sys, numpy as np
sys.path.insert(0, \"/home/gabe/astroplanner\")
from astroplanner import _update_preview
import os

img = np.random.randint(500, 30000, (1080, 1920), dtype=np.uint16)
running = _update_preview(img, \"/tmp/fits_test/preview.png\", 1, None)
print(f\"Preview saved, running_sum shape: {running.shape}\")
print(f\"File exists: {os.path.exists(\"/tmp/fits_test/preview.png\")}\")
"'
```
Expected: Preview saved, file exists.

**Step 5: Test CLI flag parsing**

```bash
ssh gabe@haight '/home/gabe/astroplanner/.venv/bin/python /home/gabe/astroplanner/astroplanner.py --help 2>&1 | grep -E "exposure|observe|target"'
```
Expected: Shows `--exposure`, `--observe`, and `--target` flags.

**Step 6: Commit any fixes if needed**

---

### Task 7: Live telescope test (when telescope is available)

**Files:** none (manual test)

**Dependencies:** Task 6

**Step 1: Quick exposure test**

Connect to the telescope, take 1 exposure, save as FITS, verify the image:

```bash
ssh gabe@haight '/home/gabe/astroplanner/.venv/bin/python -c "
import sys, os
sys.path.insert(0, \"/home/gabe/astroplanner\")
from astroplanner import SeestarTelescope, _save_fits
from datetime import datetime, timezone

scope = SeestarTelescope(\"192.168.1.216\", 32323)
scope.connect()
print(\"Connected\")

print(\"Exposing 10s...\")
ok = scope.expose(10.0)
print(f\"Expose result: {ok}\")

if ok:
    img, err = scope.download_image()
    if img is not None:
        print(f\"Image shape: {img.shape}, min={img.min()}, max={img.max()}\")
        os.makedirs(\"/tmp/live_test\", exist_ok=True)
        f = _save_fits(img, \"/tmp/live_test\", \"test\", 1, 0, 0, 10.0, \"IR\",
                       datetime.now(timezone.utc))
        print(f\"Saved: {f}\")
    else:
        print(f\"Download error: {err}\")

scope.disconnect()
"'
```

**Step 2: If test passes, run a short observe session**

```bash
ssh gabe@haight '/home/gabe/astroplanner/.venv/bin/python /home/gabe/astroplanner/astroplanner.py --observe --target M13 --exposure 10'
```

Watch the output for: frames saving, preview updating, no crashes.
