# Astroplanner

Deep sky object visibility planner for the Seestar S50 smart telescope, optimized for suburban skies (Bortle 7-8).

Plans nightly observation windows for ~140 DSOs (complete Messier catalog + select NGC/IC targets), scoring each by altitude, moon conditions, stacking time, and object difficulty.

## Features

- **Nightly plans** — ranked targets with observation windows, peak altitudes, and moon impact
- **Tonight mode** — detailed imaging notes with per-object tips
- **Best-nights mode** — find the optimal night for each DSO across a date range
- **Weekly forecast** — 7-day outlook combining weather (NWS API), moon phase, and target availability
- **Email alerts** — cron-friendly mode that sends a report when conditions meet a threshold
- **ISS lunar transit prediction** — searches for ISS passes across the lunar disk (requires skyfield)
- **Type filtering** — focus on galaxies, emission nebulae, globulars, etc.

## Install

```bash
pip install astropy tabulate

# Optional: for ISS lunar transit predictions
pip install skyfield
```

## Usage

```bash
# 30-day plan (default)
python astroplanner.py

# Tonight's targets with detailed notes
python astroplanner.py --tonight

# Best night per object over 60 days
python astroplanner.py --best-nights --days 60

# Only galaxies
python astroplanner.py --type galaxy

# 7-day forecast with weather
python astroplanner.py --week

# ISS lunar transit search
python astroplanner.py --iss-transits --days 30

# Email alert for cron (sends if conditions are "good" or better)
python astroplanner.py --alert --min-grade good
```

### CLI options

| Flag | Default | Description |
|------|---------|-------------|
| `--days N` | 30 | Number of days to plan ahead |
| `--min-alt DEG` | 35 | Minimum object altitude in degrees |
| `--min-moon-sep DEG` | 30 | Minimum moon separation in degrees |
| `--top N` | 10 | Number of targets to show per night |
| `--type TYPE` | all | Filter: `emission`, `galaxy`, `globular`, `planetary`, `open cluster`, etc. |
| `--tonight` | | Detailed plan for tonight only |
| `--best-nights` | | Show the single best night for each DSO |
| `--week` | | 7-day imaging forecast with weather |
| `--alert` | | Evaluate tonight and email/print a report |
| `--min-grade GRADE` | fair | Minimum grade to trigger alert (`poor`/`fair`/`good`/`excellent`) |
| `--iss-transits` | | Search for ISS lunar transits |

## Email alerts

Set these environment variables to enable email delivery (otherwise reports print to stdout):

```bash
export ASTRO_EMAIL_TO="you@example.com"
export ASTRO_EMAIL_FROM="sender@gmail.com"
export ASTRO_EMAIL_PASS="app-password"
export ASTRO_SMTP_HOST="smtp.gmail.com"   # optional, default
export ASTRO_SMTP_PORT="587"              # optional, default
```

Example cron entry to check every day at 4 PM:

```
0 16 * * * python3 /path/to/astroplanner.py --alert
```

## Configuration

Location, elevation, and timezone are hardcoded near the top of `astroplanner.py`:

```python
LATITUDE = 37.3688       # Sunnyvale, CA
LONGITUDE = -122.0363
ELEVATION = 30           # meters
TIMEZONE_OFFSET = -7     # PDT (change to -8 for PST)
```

Edit these to match your observing site.

## How scoring works

Each target gets a 0-100 score based on:

- **Peak altitude** (30%) — higher = less atmosphere and light pollution gradient
- **Moon illumination** (25%) — sensitivity varies by object type (nebulae are penalized heavily, clusters barely affected)
- **Moon separation** (15%) — distance from moon; ignored if moon is below horizon or very dim
- **Window duration** (20%) — longer stacking time = better signal-to-noise
- **Difficulty** (10%) — easier objects score higher for equivalent conditions

## License

MIT
