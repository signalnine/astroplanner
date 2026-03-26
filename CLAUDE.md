# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What This Is

Single-file Python application (`astroplanner.py`) that plans deep sky object (DSO) observations for a Seestar S50 telescope. Hardcoded for Sunnyvale, CA (Bortle 7-8 light pollution). Uses astropy for astronomical computations and optionally skyfield for ISS lunar transit predictions.

## Running

```bash
# Install dependencies
pip install astropy tabulate

# Optional: for ISS lunar transit predictions
pip install skyfield

# Basic usage (30-day plan)
python astroplanner.py

# Tonight only with detailed notes
python astroplanner.py --tonight

# Best night per object over date range
python astroplanner.py --best-nights --days 60

# Filter by object type
python astroplanner.py --type galaxy
python astroplanner.py --type emission

# 7-day forecast with weather integration
python astroplanner.py --week

# Email alert mode (for cron)
python astroplanner.py --alert --min-grade good

# ISS lunar transit search
python astroplanner.py --iss-transits --days 30
```

## Architecture

Everything is in `astroplanner.py` (~1630 lines). No tests, no build system.

**Key sections in order:**
1. **Configuration** (lines ~42-47): Hardcoded lat/lon/elevation/timezone for Sunnyvale, CA
2. **DSO Catalog** (lines ~56-193): ~140 objects (complete Messier + select NGC/IC). Each entry has: name, common name, RA/Dec, type, magnitude, size, difficulty (1-5), notes
3. **Scoring model** (`score_observation`): Weighted 0-100 score based on altitude, moon illumination, moon separation, window duration, difficulty, and object type. Moon sensitivity varies by type (nebulae penalized more than clusters)
4. **Astronomical computations** (`find_darkness_window`, `compute_night_batch`): Batch-vectorized transforms using astropy — all objects x all time samples in one `transform_to` call per night
5. **ISS lunar transit prediction** (`find_iss_lunar_transits`): Uses skyfield + TLE data. Coarse 1s scan then 0.02s refinement around close approaches
6. **Weather + alerts** (`fetch_night_weather`, `run_alert`, `run_week`): NWS API (free, US-only, no key needed). Email alerts via SMTP env vars (`ASTRO_EMAIL_TO`, `ASTRO_EMAIL_FROM`, `ASTRO_EMAIL_PASS`)
7. **Main/CLI** (`main`): argparse with modes: default nightly plan, `--tonight`, `--best-nights`, `--week`, `--alert`, `--iss-transits`

**External data file:** `de421.bsp` — JPL planetary ephemeris used by skyfield (gitignored via `*.bsp` pattern but present in working dir).

## Key Design Decisions

- All astropy coordinate transforms are batched/vectorized (N objects x M time samples in one call) for performance — avoid introducing per-object loops around `transform_to`
- Moon position computed once per night at mid-darkness (moves negligibly in a few hours)
- Object type affects moon sensitivity in scoring: emission/dark nebulae get full moon penalty, clusters get minimal penalty
- `TIMEZONE_OFFSET` is hardcoded to -7 (PDT); must be manually changed to -8 for PST
