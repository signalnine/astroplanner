# FITS Sub-frame Acquisition for --observe Mode

## Problem

The Seestar S50's native live stacking is only available through the phone app or
the legacy JSON-RPC protocol (port 4700), which firmware 7.x blocks for third-party
apps. The Alpaca API's `startexposure` command takes individual exposures but does
not trigger the Seestar's internal stacking pipeline. Images from Alpaca exposures
don't appear in the phone app's album.

## Solution

Replace the current `start_stacking` call with a continuous exposure loop that saves
each sub-frame as a FITS file with rich metadata. Users stack the FITS files with
dedicated tools (Siril, DeepSkyStacker, PixInsight) that handle alignment, field
rotation correction, calibration, and rejection far better than we could.

## Design Decisions (via multi-agent consensus)

1. **Exposure strategy**: `--exposure` CLI flag, default 10s. The Seestar's proven
   default for Bortle 7-8 DSOs. Clamped to 1-30s with a warning outside that range.

2. **No in-app stacking**: Save raw sub-frames, let dedicated tools stack. Our value
   is automation (unattended target selection, slew, filter, all-night acquisition),
   not image processing.

3. **No alignment**: The Seestar S50 is Alt-Az (field rotates ~120px/hour at edges).
   Proper alignment requires star detection + affine transforms that dedicated tools
   already do well. We save frames, they align them.

4. **Preview only**: Simple unaligned mean-stack preview PNG updated every 50 frames
   for quick "is data accumulating?" feedback. Not science-grade.

5. **Keep telescope awake**: User must disable auto power-off in the Seestar app
   settings before first session. Continuous exposure cycling (no idle gaps) as
   secondary measure.

## Exposure Loop

Each cycle (~20-25s total):
1. `PUT camera/0/startexposure` (Duration=10, Light=true)
2. Poll `GET camera/0/imageready` every 1s until true
3. `GET camera/0/imagearray` -- returns ~9MB JSON, parse to numpy array
4. Save as FITS with headers
5. Every 50 frames, update mean-stack preview PNG
6. Check altitude and dark window -- continue, switch target, or end session

Estimated throughput: ~150-180 frames/hour, ~1200-1400 over 8 hours.

## FITS Headers

Each frame includes:
- OBJECT: target name (e.g. "M94")
- RA, DEC: J2000 coordinates in degrees
- DATE-OBS: ISO 8601 UTC timestamp
- EXPTIME: exposure duration in seconds
- FILTER: "LP" (dual-band), "IR" (clear), or "Dark"
- FRAME: sequence number (1-indexed)
- INSTRUME: "Seestar S50"
- TELESCOP: "ZWO Seestar S50"
- FOCALLEN: 463 (mm)
- APERTURE: 50 (mm)
- SITELAT, SITELONG: observer location

## Output Structure

```
~/astroplanner/captures/
  2026-04-09_M94/
    M94_0001.fits
    M94_0002.fits
    ...
    preview.png       (updated every 50 frames)
```

## Changes to Existing Code

### SeestarTelescope class
- Remove `start_stacking()` and `stop_stacking()` methods
- Add `expose(duration)` -- starts exposure and waits for completion
- Add `download_image()` -- downloads imagearray as numpy array
- Add `get_camera_state()` -- returns camera state enum

### run_observe()
- Add `--exposure` CLI flag (default 10.0, range 1-30)
- Create output directory at session start
- Replace stacking logic with exposure loop

### _observe_target()
- Replace "start stacking + monitor" with "expose + save FITS" loop
- Save each frame immediately after download
- Update preview every 50 frames
- Check altitude/dark window between exposures

### --tonight output
- Add "Disable auto power-off in Seestar app" to setup instructions

## What We're NOT Building

- No alignment, registration, or rotation correction
- No dark/flat/bias calibration
- No star detection or quality scoring
- No sigma-clipped stacking (preview is simple mean only)
- No competing with Siril/DSS/PixInsight

## Dependencies

- astropy.io.fits (already available via astropy)
- PIL/Pillow for preview PNG (already installed on haight)
- numpy (already available via astropy)
