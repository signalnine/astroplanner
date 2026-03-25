#!/usr/bin/env python3
"""
seestar_planner.py — Deep sky object visibility planner for Seestar S50
Optimized for Sunnyvale, CA (Bortle 7-8)

Computes nightly observation windows for DSOs, accounting for:
  - Object altitude (configurable minimum, default 35°)
  - Astronomical darkness (Sun below -18°)
  - Moon illumination and angular separation
  - Transit time (when object is highest)
  - Seasonal visibility

Dependencies: pip install astropy tabulate
Usage: python seestar_planner.py [--days 30] [--min-alt 35] [--min-moon-sep 30]
"""

import argparse
import math
import sys
import warnings
from datetime import datetime, timedelta, timezone

import numpy as np
from astropy.coordinates import (
    AltAz,
    EarthLocation,
    SkyCoord,
    get_body,
    get_sun,
)
from astropy.time import Time
import astropy.units as u

# suppress astropy IERS download warnings in offline environments
warnings.filterwarnings("ignore", category=UserWarning)
warnings.filterwarnings("ignore", message=".*IERS.*")

# ──────────────────────────────────────────────────────────────────────
# Configuration — edit these to match your setup
# ──────────────────────────────────────────────────────────────────────

LATITUDE = 37.3688       # Sunnyvale, CA
LONGITUDE = -122.0363
ELEVATION = 30           # meters
TIMEZONE_OFFSET = -7     # PDT (change to -8 for PST)
TIMEZONE_NAME = "PDT"

# ──────────────────────────────────────────────────────────────────────
# DSO catalog — complete Messier (M1-M110) plus select NGC/IC targets
# Optimized for Seestar S50 (50mm aperture, stacking, LP filter)
#
# Columns: name, common_name, ra (hms), dec (dms), type, mag, size_arcmin,
#          difficulty (1=easy/5=hard for Seestar in Bortle 7-8), notes
# ──────────────────────────────────────────────────────────────────────

DSO_CATALOG = [
    # ── EMISSION / REFLECTION NEBULAE ──
    ("M42",    "Orion Nebula",           "05h35m17.3s", "-05d23m28s", "emission",   4.0,  85, 1, "the showpiece — incredible even in LP"),
    ("M43",    "De Mairan's Nebula",     "05h35m31.0s", "-05d16m00s", "emission",   9.0,   5, 2, "companion to M42, capture together"),
    ("NGC1977","Running Man Nebula",     "05h35m16.0s", "-04d52m00s", "reflection", 7.0,  20, 2, "reflection nebula near M42"),
    ("IC434",  "Horsehead Nebula",       "05h40m59.0s", "-02d27m30s", "dark",       6.8,  60, 3, "Seestar LP filter helps enormously"),
    ("M1",     "Crab Nebula",            "05h34m31.9s", "+22d00m52s", "SNR",        8.4,   6, 2, "supernova remnant, small but bright"),
    ("M78",    "Casper the Ghost",       "05h46m46.7s", "+00d00m50s", "reflection", 8.3,   8, 3, "reflection nebula in Orion"),
    ("NGC2024","Flame Nebula",           "05h41m54.0s", "-01d51m00s", "emission",   2.0,  30, 2, "next to Alnitak, LP filter essential"),
    ("M8",     "Lagoon Nebula",          "18h03m37.0s", "-24d23m12s", "emission",   6.0,  90, 1, "summer showpiece, huge and bright"),
    ("M20",    "Trifid Nebula",          "18h02m23.0s", "-23d01m48s", "emission",   6.3,  28, 2, "near M8, emission + reflection"),
    ("M17",    "Omega/Swan Nebula",      "18h20m26.0s", "-16d10m36s", "emission",   6.0,  11, 1, "very bright, great Seestar target"),
    ("M16",    "Eagle Nebula",           "18h18m48.0s", "-13d47m00s", "emission",   6.0,  35, 2, "pillars of creation — needs stacking"),
    ("NGC7000","North America Nebula",   "20h58m47.0s", "+44d19m48s", "emission",   4.0, 120, 3, "enormous, Seestar captures the Gulf region"),
    ("IC5070", "Pelican Nebula",         "20h50m48.0s", "+44d21m00s", "emission",   8.0,  60, 3, "companion to NGC7000"),
    ("NGC6960","Western Veil Nebula",    "20h45m38.0s", "+30d42m30s", "SNR",        7.0,  70, 2, "LP filter is a game-changer here"),
    ("NGC6992","Eastern Veil Nebula",    "20h56m24.0s", "+31d43m00s", "SNR",        7.0,  60, 2, "other half of the Veil"),
    ("M27",    "Dumbbell Nebula",        "19h59m36.3s", "+22d43m16s", "planetary",  7.5,   8, 1, "bright planetary nebula, easy win"),
    ("M57",    "Ring Nebula",            "18h53m35.1s", "+33d01m45s", "planetary",  8.8,   1, 2, "tiny but iconic, Seestar resolves the ring"),
    ("NGC6888","Crescent Nebula",        "20h12m07.0s", "+38d21m18s", "emission",   7.4,  18, 3, "LP filter target"),
    ("M76",    "Little Dumbbell",        "01h42m19.9s", "+51d34m31s", "planetary", 10.1,   2, 4, "small and faint, challenge object"),
    ("NGC281", "Pacman Nebula",          "00h52m59.3s", "+56d37m19s", "emission",   7.4,  35, 3, "Ha target, LP filter helps"),
    ("IC1396", "Elephant's Trunk",       "21h39m06.0s", "+57d30m00s", "emission",   3.5, 170, 3, "huge, Seestar captures the trunk"),
    ("NGC2237","Rosette Nebula",         "06h32m24.0s", "+05d03m00s", "emission",   9.0,  80, 2, "winter/spring target, LP filter star"),
    ("NGC2264","Cone + Christmas Tree",  "06h41m06.0s", "+09d53m00s", "emission",   3.9,  20, 3, "cluster + nebulosity"),
    ("M97",    "Owl Nebula",             "11h14m47.7s", "+55d01m09s", "planetary",  9.9,   3, 3, "face-on planetary, fun target"),

    # ── GALAXIES ──
    ("M31",    "Andromeda Galaxy",       "00h42m44.3s", "+41d16m09s", "galaxy",     3.4, 190, 1, "too big for one frame, mosaic the core"),
    ("M32",    "Andromeda Satellite",    "00h42m41.8s", "+40d51m55s", "galaxy",     8.1,   8, 2, "compact companion to M31"),
    ("M33",    "Triangulum Galaxy",      "01h33m50.9s", "+30d39m37s", "galaxy",     5.7,  73, 2, "face-on spiral, needs dark skies ideally"),
    ("M49",    "Virgo A Elliptical",     "12h29m46.7s", "+08d00m02s", "galaxy",     8.4,  10, 3, "brightest Virgo cluster galaxy"),
    ("M51",    "Whirlpool Galaxy",       "13h29m52.7s", "+47d11m43s", "galaxy",     8.4,  11, 2, "face-on spiral pair, Seestar classic"),
    ("M58",    "Barred Spiral in Virgo", "12h37m43.5s", "+11d49m05s", "galaxy",     9.7,   6, 4, "Virgo cluster barred spiral"),
    ("M59",    "Elliptical in Virgo",    "12h42m02.3s", "+11d38m49s", "galaxy",     9.6,   5, 4, "Virgo elliptical, small"),
    ("M60",    "Elliptical in Virgo",    "12h43m40.0s", "+11d33m09s", "galaxy",     8.8,   7, 3, "pair with NGC4647 in same FOV"),
    ("M61",    "Spiral in Virgo",        "12h21m54.9s", "+04d28m25s", "galaxy",     9.7,   6, 4, "face-on spiral, faint"),
    ("M63",    "Sunflower Galaxy",       "13h15m49.3s", "+42d01m45s", "galaxy",     8.6,  13, 3, "flocculent spiral"),
    ("M64",    "Black Eye Galaxy",       "12h56m43.7s", "+21d40m58s", "galaxy",     8.5,  10, 2, "dark dust lane visible"),
    ("M65",    "Leo Triplet - M65",      "11h18m55.9s", "+13d05m32s", "galaxy",     9.3,  10, 2, "part of Leo Triplet"),
    ("M66",    "Leo Triplet - M66",      "11h20m15.0s", "+12d59m30s", "galaxy",     8.9,   9, 2, "brightest of Leo Triplet"),
    ("NGC3628","Leo Triplet - Hamburger", "11h20m17.0s", "+13d35m23s", "galaxy",    9.5,  15, 3, "edge-on, low surface brightness"),
    ("M74",    "Phantom Galaxy",         "01h36m41.7s", "+15d47m01s", "galaxy",     9.4,  10, 5, "notoriously low surface brightness"),
    ("M77",    "Cetus A",               "02h42m40.7s", "-00d00m48s", "galaxy",     8.9,   7, 3, "Seyfert galaxy with active nucleus"),
    ("M81",    "Bode's Galaxy",          "09h55m33.2s", "+69d03m55s", "galaxy",     6.9,  27, 1, "bright spiral, pairs with M82"),
    ("M82",    "Cigar Galaxy",           "09h55m52.2s", "+69d40m47s", "galaxy",     8.4,  11, 1, "starburst galaxy, dramatic"),
    ("M83",    "Southern Pinwheel",      "13h37m00.9s", "-29d51m57s", "galaxy",     7.5,  13, 3, "low dec from Sunnyvale, narrow window"),
    ("M84",    "Markarian's Chain",      "12h25m03.7s", "+12d53m13s", "galaxy",     9.1,   6, 3, "lenticular, start of Markarian's Chain"),
    ("M85",    "Lenticular in Coma",     "12h25m24.0s", "+18d11m28s", "galaxy",     9.1,   7, 3, "northernmost Virgo cluster member"),
    ("M86",    "Eyes of Markarian",      "12h26m11.7s", "+12d56m46s", "galaxy",     8.9,   9, 3, "elliptical, near M84 in same FOV"),
    ("M87",    "Virgo A Jet Galaxy",     "12h30m49.4s", "+12d23m28s", "galaxy",     8.6,   7, 3, "famous jet galaxy"),
    ("M88",    "Spiral in Coma",         "12h31m59.2s", "+14d25m14s", "galaxy",     9.6,   7, 3, "multi-arm spiral"),
    ("M89",    "Elliptical in Virgo",    "12h35m39.8s", "+12d33m23s", "galaxy",     9.8,   5, 4, "nearly round elliptical"),
    ("M90",    "Spiral in Virgo",        "12h36m49.8s", "+13d09m46s", "galaxy",     9.5,  10, 3, "large spiral, one of few blueshifted"),
    ("M91",    "Barred Spiral in Coma",  "12h35m26.4s", "+14d29m47s", "galaxy",    10.2,   5, 5, "faintest Messier galaxy, challenge"),
    ("M94",    "Cat's Eye Galaxy",       "12h50m53.1s", "+41d07m14s", "galaxy",     8.2,  11, 2, "bright compact core with outer ring"),
    ("M95",    "Barred Spiral in Leo",   "10h43m57.7s", "+11d42m14s", "galaxy",     9.7,   7, 3, "Leo I group, bar visible with stacking"),
    ("M96",    "Spiral in Leo",          "10h46m45.7s", "+11d49m12s", "galaxy",     9.2,   8, 3, "Leo I group, brightest of trio"),
    ("M98",    "Spiral in Coma",         "12h13m48.3s", "+14d54m01s", "galaxy",    10.1,  10, 4, "nearly edge-on, low surface brightness"),
    ("M99",    "Coma Pinwheel",          "12h18m49.6s", "+14d24m59s", "galaxy",     9.9,   5, 4, "face-on spiral, needs long stacking"),
    ("M100",   "Mirror Galaxy",          "12h22m54.9s", "+15d49m21s", "galaxy",     9.3,   7, 3, "grand-design spiral in Virgo"),
    ("M101",   "Pinwheel Galaxy",        "14h03m12.6s", "+54d20m57s", "galaxy",     7.9,  29, 3, "face-on, low surface brightness"),
    ("M102",   "Spindle Galaxy",         "15h06m29.5s", "+55d45m48s", "galaxy",     9.9,   6, 3, "edge-on lenticular with dust lane"),
    ("M104",   "Sombrero Galaxy",        "12h39m59.4s", "-11d37m23s", "galaxy",     8.0,   9, 2, "edge-on with dust lane"),
    ("M105",   "Elliptical in Leo",      "10h47m49.6s", "+12d34m54s", "galaxy",     9.3,   5, 3, "Leo I group, near M95/M96"),
    ("M106",   "Seyfert Galaxy",         "12h18m57.5s", "+47d18m14s", "galaxy",     8.4,  19, 2, "active galaxy with jets"),
    ("M108",   "Surfboard Galaxy",       "11h11m31.0s", "+55d40m27s", "galaxy",    10.0,   8, 3, "edge-on near M97 Owl Nebula"),
    ("M109",   "Barred Spiral in UMa",   "11h57m35.8s", "+53d22m28s", "galaxy",     9.8,   8, 3, "barred spiral near Phecda"),
    ("M110",   "Andromeda Satellite II", "00h40m22.1s", "+41d41m07s", "galaxy",     8.5,  22, 2, "dwarf elliptical near M31"),
    ("NGC2903","Barred Spiral in Leo",   "09h32m10.1s", "+21d30m03s", "galaxy",     9.0,  13, 3, "underrated barred spiral"),
    ("NGC4565","Needle Galaxy",          "12h36m20.8s", "+25d59m16s", "galaxy",     9.6,  16, 3, "edge-on beauty"),
    ("NGC4631","Whale Galaxy",           "12h42m08.0s", "+32d32m29s", "galaxy",     9.2,  15, 3, "edge-on with companion NGC4627"),

    # ── OPEN CLUSTERS ──
    ("M6",     "Butterfly Cluster",      "17h40m20.0s", "-32d15m12s", "open cluster", 4.2,  25, 2, "low from Sunnyvale, summer"),
    ("M7",     "Ptolemy's Cluster",      "17h53m51.2s", "-34d47m34s", "open cluster", 3.3,  80, 3, "very low dec, needs clear south horizon"),
    ("M11",    "Wild Duck Cluster",      "18h51m05.0s", "-06d16m12s", "open cluster", 6.3,  14, 1, "one of richest open clusters"),
    ("M18",    "Open Cluster in Sgr",    "18h19m58.0s", "-17d06m07s", "open cluster", 7.5,   9, 3, "small sparse cluster near M17"),
    ("M21",    "Open Cluster in Sgr",    "18h04m13.0s", "-22d29m24s", "open cluster", 6.5,  13, 2, "near M20 Trifid, capture together"),
    ("M23",    "Open Cluster in Sgr",    "17h56m55.0s", "-19d01m09s", "open cluster", 6.9,  27, 2, "rich summer cluster"),
    ("M24",    "Sagittarius Star Cloud", "18h16m54.0s", "-18d33m00s", "open cluster", 4.6,  90, 2, "dense Milky Way star cloud"),
    ("M25",    "Open Cluster in Sgr",    "18h31m47.0s", "-19d07m00s", "open cluster", 6.5,  32, 2, "contains Cepheid variable U Sgr"),
    ("M26",    "Open Cluster in Scutum", "18h45m18.0s", "-09d23m00s", "open cluster", 8.0,  15, 3, "faint cluster near M11"),
    ("M29",    "Cooling Tower Cluster",  "20h23m57.0s", "+38d30m30s", "open cluster", 7.1,   7, 3, "small sparse cluster in Cygnus"),
    ("M34",    "Open Cluster in Perseus","02h42m07.0s", "+42d44m46s", "open cluster", 5.5,  35, 1, "bright easy cluster, autumn"),
    ("M35",    "Open Cluster in Gemini", "06h08m54.0s", "+24d20m00s", "open cluster", 5.3,  28, 1, "rich cluster, easy target"),
    ("M36",    "Pinwheel Cluster",       "05h36m18.0s", "+34d08m24s", "open cluster", 6.3,  12, 1, "Auriga trio with M37 and M38"),
    ("M37",    "Salt and Pepper Cluster","05h52m18.0s", "+32d33m12s", "open cluster", 6.2,  24, 1, "richest of the Auriga trio"),
    ("M38",    "Starfish Cluster",       "05h28m43.0s", "+35d51m18s", "open cluster", 7.0,  21, 2, "Auriga trio, looser than M36/M37"),
    ("M39",    "Open Cluster in Cygnus", "21h31m48.0s", "+48d26m00s", "open cluster", 4.6,  32, 1, "large loose cluster, autumn"),
    ("M41",    "Open Cluster in CMa",    "06h46m01.0s", "-20d45m24s", "open cluster", 4.5,  38, 1, "bright winter cluster near Sirius"),
    ("M44",    "Beehive Cluster",        "08h40m24.0s", "+19d40m00s", "open cluster", 3.7,  95, 1, "large, bright, springtime"),
    ("M45",    "Pleiades",              "03h47m24.0s", "+24d07m00s", "open cluster", 1.6, 110, 1, "nebulosity visible with stacking"),
    ("M46",    "Open Cluster in Puppis", "07h41m46.0s", "-14d48m36s", "open cluster", 6.1,  27, 2, "contains planetary nebula NGC2438"),
    ("M47",    "Open Cluster in Puppis", "07h36m35.0s", "-14d28m57s", "open cluster", 4.4,  30, 1, "bright, pairs with nearby M46"),
    ("M48",    "Open Cluster in Hydra",  "08h13m43.0s", "-05d45m02s", "open cluster", 5.8,  54, 2, "large scattered cluster"),
    ("M50",    "Open Cluster in Mon",    "07h02m42.0s", "-08d23m27s", "open cluster", 5.9,  16, 2, "winter cluster in Monoceros"),
    ("M52",    "Open Cluster in Cas",    "23h24m48.0s", "+61d35m36s", "open cluster", 7.3,  13, 2, "near Bubble Nebula region"),
    ("M67",    "King Cobra Cluster",     "08h51m18.0s", "+11d48m00s", "open cluster", 6.1,  30, 2, "one of oldest known open clusters"),
    ("M93",    "Open Cluster in Puppis", "07h44m30.0s", "-23d51m24s", "open cluster", 6.0,  22, 2, "bright winter cluster"),
    ("M103",   "Open Cluster in Cas",    "01h33m23.0s", "+60d39m00s", "open cluster", 7.4,   6, 2, "small cluster near Cassiopeia"),
    ("NGC884", "Double Cluster h+chi",   "02h22m18.0s", "+57d08m12s", "open cluster", 6.1,  60, 1, "stunning pair of clusters"),

    # ── GLOBULAR CLUSTERS ──
    ("M2",     "Globular in Aquarius",   "21h33m27.0s", "-00d49m24s", "globular",   6.5,  16, 2, "autumn globular, compact core"),
    ("M3",     "Globular in CVn",        "13h42m11.6s", "+28d22m39s", "globular",   6.2,  18, 1, "spring glob, high in sky"),
    ("M4",     "Globular in Scorpius",   "16h23m35.2s", "-26d31m33s", "globular",   5.6,  36, 2, "very low from Sunnyvale"),
    ("M5",     "Globular in Serpens",    "15h18m33.2s", "+02d04m52s", "globular",   5.7,  23, 1, "beautiful, rivals M13"),
    ("M9",     "Globular in Ophiuchus",  "17h19m11.8s", "-18d30m59s", "globular",   8.4,  12, 3, "small but resolved with stacking"),
    ("M10",    "Globular in Ophiuchus",  "16h57m08.9s", "-04d06m01s", "globular",   6.6,  20, 2, "summer globular, pairs with M12"),
    ("M12",    "Globular in Ophiuchus",  "16h47m14.2s", "-01d56m55s", "globular",   6.6,  16, 2, "looser than M10, easy to resolve"),
    ("M13",    "Great Hercules Cluster", "16h41m41.6s", "+36d27m41s", "globular",   5.8,  20, 1, "the best glob from northern latitudes"),
    ("M14",    "Globular in Ophiuchus",  "17h37m36.2s", "-03d14m45s", "globular",   7.6,  11, 3, "dimmer Ophiuchus globular"),
    ("M15",    "Globular in Pegasus",    "21h29m58.3s", "+12d10m01s", "globular",   6.2,  18, 2, "autumn glob, dense core"),
    ("M19",    "Globular in Ophiuchus",  "17h02m37.7s", "-26d16m05s", "globular",   7.2,  17, 3, "elongated shape, low dec"),
    ("M22",    "Sagittarius Cluster",    "18h36m24.2s", "-23d54m17s", "globular",   5.1,  32, 2, "third brightest glob, low from Sunnyvale"),
    ("M28",    "Globular in Sagittarius","18h24m32.9s", "-24d52m12s", "globular",   6.8,  11, 3, "compact, near M22"),
    ("M30",    "Globular in Capricornus","21h40m22.1s", "-23d10m47s", "globular",   7.2,  12, 3, "autumn glob, low dec"),
    ("M53",    "Globular in Coma",       "13h12m55.3s", "+18d10m06s", "globular",   7.6,  13, 3, "distant globular, 60k light-years"),
    ("M54",    "Sagittarius Dwarf Glob", "18h55m03.3s", "-30d28m42s", "globular",   7.6,  12, 4, "very low dec, extragalactic origin"),
    ("M55",    "Summer Rose Star",       "19h39m59.4s", "-30d57m44s", "globular",   6.3,  19, 3, "very low from Sunnyvale, needs south"),
    ("M56",    "Globular in Lyra",       "19h16m35.5s", "+30d11m05s", "globular",   8.3,   9, 3, "small glob near Ring Nebula"),
    ("M62",    "Globular in Ophiuchus",  "17h01m12.6s", "-30d06m45s", "globular",   6.5,  15, 3, "asymmetric core, very low dec"),
    ("M68",    "Globular in Hydra",      "12h39m27.9s", "-26d44m35s", "globular",   7.8,  11, 3, "low dec spring target"),
    ("M69",    "Globular in Sagittarius","18h31m23.2s", "-32d20m53s", "globular",   7.6,  10, 4, "very low from Sunnyvale"),
    ("M70",    "Globular in Sagittarius","18h43m12.6s", "-32d17m31s", "globular",   7.9,   8, 4, "very low, near M69"),
    ("M71",    "Globular in Sagitta",    "19h53m46.5s", "+18d46m42s", "globular",   8.2,   7, 3, "loose glob, resembles open cluster"),
    ("M72",    "Globular in Aquarius",   "20h53m27.9s", "-12d32m14s", "globular",   9.3,   6, 4, "small faint globular"),
    ("M75",    "Globular in Sagittarius","20h06m04.8s", "-21d55m17s", "globular",   8.5,   7, 4, "small distant globular"),
    ("M79",    "Globular in Lepus",      "05h24m10.6s", "-24d31m27s", "globular",   7.7,   9, 3, "winter globular, unusual southern position"),
    ("M80",    "Globular in Scorpius",   "16h17m02.4s", "-22d58m34s", "globular",   7.3,  10, 3, "dense core, near Antares"),
    ("M92",    "Globular in Hercules",   "17h17m07.4s", "+43d08m10s", "globular",   6.4,  14, 2, "often overlooked for M13"),
    ("M107",   "Globular in Ophiuchus",  "16h32m31.9s", "-13d03m14s", "globular",   7.9,  13, 3, "loose globular, southern summer"),

    # ── ASTERISMS / ODDITIES (included for Messier completeness) ──
    ("M40",    "Winnecke 4",            "12h22m12.5s", "+58d04m59s", "double star", 8.4,   1, 5, "just a double star — Messier mistake"),
    ("M73",    "Asterism in Aquarius",   "20h58m54.0s", "-12d38m08s", "asterism",   9.0,   3, 5, "4-star asterism — Messier mistake"),
]

# ──────────────────────────────────────────────────────────────────────
# Scoring model
# ──────────────────────────────────────────────────────────────────────

def score_observation(peak_alt, moon_illum_pct, moon_sep_deg, hours_above_min,
                      difficulty, obj_type):
    """
    Score an observation opportunity from 0-100.

    Factors (weighted):
      - Peak altitude: higher is better (less atmosphere, less LP gradient)
      - Moon illumination: lower is better
      - Moon separation: farther is better
      - Window duration: longer stacking time = better result
      - Object difficulty: easier objects score higher for same conditions
      - Object type: nebulae benefit more from dark skies than clusters
    """
    # Altitude score (35°=0.3, 60°=0.75, 90°=1.0)
    alt_score = min(1.0, max(0, (peak_alt - 20) / 70))

    # Moon illumination penalty
    # New moon (0%) = 1.0, full (100%) = 0.0
    # But the penalty is type-dependent: nebulae suffer more than clusters
    moon_sensitivity = {
        "emission": 1.0, "dark": 1.0, "reflection": 0.9,
        "SNR": 0.9, "planetary": 0.6, "galaxy": 0.8,
        "globular": 0.3, "open cluster": 0.2,
    }
    sensitivity = moon_sensitivity.get(obj_type, 0.7)
    moon_illum_score = 1.0 - (moon_illum_pct / 100) * sensitivity

    # Moon separation score (< 30° is bad, > 60° is fine)
    if moon_sep_deg < 15:
        moon_sep_score = 0.1
    elif moon_sep_deg < 30:
        moon_sep_score = 0.3 + 0.4 * (moon_sep_deg - 15) / 15
    elif moon_sep_deg < 60:
        moon_sep_score = 0.7 + 0.2 * (moon_sep_deg - 30) / 30
    else:
        moon_sep_score = 0.9 + 0.1 * min(1, (moon_sep_deg - 60) / 60)

    # If moon is below horizon or very dim, separation doesn't matter much
    if moon_illum_pct < 10:
        moon_sep_score = max(moon_sep_score, 0.9)

    # Duration score (more stacking time = better SNR)
    # 1hr = decent, 3hr+ = great
    dur_score = min(1.0, hours_above_min / 4.0)

    # Difficulty adjustment (easy objects are more rewarding in LP)
    diff_score = 1.0 - (difficulty - 1) * 0.1  # 1->1.0, 5->0.6

    # Weighted combination
    score = (
        alt_score * 30 +
        moon_illum_score * 25 +
        moon_sep_score * 15 +
        dur_score * 20 +
        diff_score * 10
    )

    return round(min(100, max(0, score)), 1)


def score_label(score):
    if score >= 75:
        return "★★★ excellent"
    elif score >= 55:
        return "★★  good"
    elif score >= 40:
        return "★   fair"
    else:
        return "    poor"


# ──────────────────────────────────────────────────────────────────────
# Astronomical computations
# ──────────────────────────────────────────────────────────────────────

def parse_catalog_coords(catalog):
    """Pre-parse all catalog RA/Dec strings into a single SkyCoord array."""
    return SkyCoord(
        ra=[entry[2] for entry in catalog],
        dec=[entry[3] for entry in catalog],
    )


def find_darkness_window(location, date_utc, tz_offset):
    """
    Find the window of astronomical darkness (sun < -18°) for a given night.
    Returns (dark_start_utc, dark_end_utc) or (None, None) if no full darkness.
    """
    # Scan from local sunset (~02:00 UTC for PDT) to sunrise (~14:00 UTC)
    # with 5-minute resolution
    start = Time(f"{date_utc.strftime('%Y-%m-%d')}T01:00:00", scale="utc")
    times = start + np.arange(0, 16 * 60, 5) * u.min

    altaz_frame = AltAz(obstime=times, location=location)
    sun_alts = get_sun(times).transform_to(altaz_frame).alt.deg

    dark_start = None
    dark_end = None
    for i, alt in enumerate(sun_alts):
        if alt < -18:
            if dark_start is None:
                dark_start = times[i]
            dark_end = times[i]

    return dark_start, dark_end


def compute_night_batch(targets, catalog, location, dark_start, dark_end,
                        min_alt, min_moon_sep, type_filter=None):
    """
    Compute visibility for ALL catalog objects in a single night, batched.

    Instead of N separate transform_to calls (one per object), this does one
    big batched transform for all objects × all time samples, plus one moon/sun
    computation per night instead of per object.
    """
    if dark_start is None or dark_end is None:
        return []

    n_obj = len(catalog)
    dt_hours = (dark_end - dark_start).to(u.hour).value
    n_samples = max(2, int(dt_hours * 6))  # every 10 min
    times = dark_start + np.linspace(0, dt_hours, n_samples) * u.hour
    n_t = len(times)

    # Build filter mask
    if type_filter:
        obj_mask = [i for i in range(n_obj) if catalog[i][4] == type_filter]
    else:
        obj_mask = list(range(n_obj))

    if not obj_mask:
        return []

    filtered_targets = targets[obj_mask]
    n_filtered = len(obj_mask)

    # Batch transform: flatten (n_filtered × n_t) into one transform_to call
    target_indices = np.repeat(np.arange(n_filtered), n_t)
    time_indices = np.tile(np.arange(n_t), n_filtered)

    targets_flat = filtered_targets[target_indices]
    times_flat = times[time_indices]

    altaz_frame = AltAz(obstime=times_flat, location=location)
    all_altaz = targets_flat.transform_to(altaz_frame)
    all_alts = all_altaz.alt.deg.reshape(n_filtered, n_t)

    # Moon/sun computed once at mid-darkness (illumination and separation
    # change negligibly over a single night)
    mid_time = times[n_t // 2]
    moon = get_body("moon", mid_time, location)
    sun = get_sun(mid_time)
    moon_altaz = moon.transform_to(AltAz(obstime=mid_time, location=location))
    moon_alt = moon_altaz.alt.deg
    elongation = moon.separation(sun)
    moon_illum = (1 - math.cos(elongation.rad)) / 2 * 100
    effective_moon_illum = moon_illum if moon_alt > 0 else moon_illum * 0.15

    # Moon separation from all filtered targets at once (vectorized)
    moon_seps = moon.separation(filtered_targets).deg

    results = []
    for idx, obj_i in enumerate(obj_mask):
        alts = all_alts[idx]
        above = alts >= min_alt
        if not np.any(above):
            continue

        peak_idx = np.argmax(alts)
        peak_alt = alts[peak_idx]
        peak_time = times[peak_idx]
        hours_above = np.sum(above) * (dt_hours / n_samples)

        above_indices = np.where(above)[0]
        window_start = times[above_indices[0]]
        window_end = times[above_indices[-1]]

        name, common, _, _, obj_type, mag, size, diff, notes = catalog[obj_i]
        moon_sep = moon_seps[idx]

        score = score_observation(
            peak_alt, effective_moon_illum, moon_sep, hours_above, diff, obj_type
        )
        moon_too_close = moon_sep < min_moon_sep and moon_alt > 0 and moon_illum > 20

        results.append({
            "name": name, "common": common, "type": obj_type,
            "mag": mag, "size": size, "difficulty": diff, "notes": notes,
            "peak_alt": peak_alt, "peak_time": peak_time,
            "window_start": window_start, "window_end": window_end,
            "hours_above": hours_above, "moon_illum": moon_illum,
            "moon_alt": moon_alt, "moon_sep": moon_sep,
            "moon_too_close": moon_too_close, "score": score,
        })

    return results


def utc_to_local(t, tz_offset):
    """Convert astropy Time to local datetime string."""
    dt = t.to_datetime(timezone=timezone(timedelta(hours=tz_offset)))
    return dt.strftime("%H:%M")


def utc_to_local_date(t, tz_offset):
    dt = t.to_datetime(timezone=timezone(timedelta(hours=tz_offset)))
    return dt.strftime("%b %d")


# ──────────────────────────────────────────────────────────────────────
# ISS lunar transit prediction
# ──────────────────────────────────────────────────────────────────────

MOON_RADIUS_KM = 1737.4
NEAR_MISS_DEG = 2.0  # report ISS passes within this distance of moon


def _angular_sep_deg(alt1, az1, alt2, az2):
    """Vectorized angular separation between alt/az pairs (all in degrees)."""
    a1, z1, a2, z2 = np.radians(alt1), np.radians(az1), np.radians(alt2), np.radians(az2)
    cos_sep = np.sin(a1) * np.sin(a2) + np.cos(a1) * np.cos(a2) * np.cos(z1 - z2)
    return np.degrees(np.arccos(np.clip(cos_sep, -1.0, 1.0)))


def fetch_iss_tle():
    """Fetch current ISS TLE. Tries Celestrak, then fallback API."""
    import json
    import urllib.request

    # Try Celestrak first (canonical source)
    try:
        url = "https://celestrak.org/NORAD/elements/gp.php?CATNR=25544&FORMAT=tle"
        response = urllib.request.urlopen(url, timeout=10)
        lines = response.read().decode().strip().split('\n')
        return lines[0].strip(), lines[1].strip(), lines[2].strip()
    except Exception:
        pass

    # Fallback: TLE API
    try:
        url = "https://tle.ivanstanojevic.me/api/tle/25544"
        response = urllib.request.urlopen(url, timeout=10)
        data = json.loads(response.read().decode())
        return data["name"], data["line1"], data["line2"]
    except Exception as e:
        print(f"  Error fetching ISS TLE: {e}")
        return None


def find_iss_lunar_transits(start_date, days):
    """
    Search for ISS lunar transits visible from observer location.

    Strategy:
      1. Fetch ISS TLE, set up skyfield ephemeris
      2. Find all ISS passes above 10° altitude
      3. For each pass, compute ISS-Moon angular separation at 1s cadence
         (moon position computed once per pass — it moves < 0.01° in 10 min)
      4. If closest approach < 2°, refine at 0.02s cadence
      5. Classify as transit (within moon disk) or near miss
    """
    try:
        from skyfield.api import load, wgs84, EarthSatellite
    except ImportError:
        print("  Error: ISS transit prediction requires skyfield.")
        print("  Install with: pip install skyfield")
        return []

    print("  Fetching ISS orbital elements from Celestrak...")
    tle = fetch_iss_tle()
    if tle is None:
        print("  Cannot predict ISS transits without current orbital data.")
        return []

    tle_name, tle_line1, tle_line2 = tle

    ts = load.timescale()
    eph = load('de421.bsp')
    earth = eph['earth']
    moon_body = eph['moon']
    sun_body = eph['sun']

    iss = EarthSatellite(tle_line1, tle_line2, tle_name, ts)
    observer = wgs84.latlon(LATITUDE, LONGITUDE, ELEVATION)

    # TLE staleness warning
    tle_epoch = iss.epoch.utc_datetime()
    days_old = (datetime.now(timezone.utc) - tle_epoch).total_seconds() / 86400
    if days_old > 7:
        print(f"  Warning: TLE is {days_old:.0f} days old — predictions beyond ~1 week are unreliable.")

    t0 = ts.utc(start_date.year, start_date.month, start_date.day)
    end_date = start_date + timedelta(days=days)
    t1 = ts.utc(end_date.year, end_date.month, end_date.day)

    print(f"  Scanning {days} days for ISS passes near the Moon...")

    # Find all ISS passes above 10°
    t_events, events = iss.find_events(observer, t0, t1, altitude_degrees=10.0)

    # Group into passes (rise=0 → set=2)
    passes = []
    current_rise = None
    for t, event in zip(t_events, events):
        if event == 0:
            current_rise = t
        elif event == 2 and current_rise is not None:
            passes.append((current_rise, t))
            current_rise = None

    print(f"  Found {len(passes)} ISS passes above 10°, checking Moon proximity...")

    results = []

    for rise_t, set_t in passes:
        # Moon position at mid-pass (moves < 0.01° during a ~10 min pass)
        mid_tt = (rise_t.tt + set_t.tt) / 2
        mid_t = ts.tt_jd(mid_tt)

        obs_pos = earth + observer
        moon_astrometric = obs_pos.at(mid_t).observe(moon_body)
        moon_apparent = moon_astrometric.apparent()
        moon_alt, moon_az, moon_dist = moon_apparent.altaz()

        # Skip if moon below 5°
        if moon_alt.degrees < 5:
            continue

        # Moon angular radius from distance
        moon_ang_radius = np.degrees(np.arctan(MOON_RADIUS_KM / moon_dist.km))

        # ISS positions at 1-second intervals through pass
        duration_s = (set_t.tt - rise_t.tt) * 86400
        n_coarse = max(3, int(duration_s))
        coarse_times = ts.linspace(rise_t, set_t, n_coarse)

        iss_topo = (iss - observer).at(coarse_times)
        iss_alt, iss_az, _ = iss_topo.altaz()

        sep = _angular_sep_deg(
            iss_alt.degrees, iss_az.degrees,
            moon_alt.degrees, moon_az.degrees,
        )

        min_idx = int(np.argmin(sep))
        if sep[min_idx] > NEAR_MISS_DEG:
            continue

        # Refine: ±10 seconds around coarse minimum at 0.02s cadence
        center_tt = coarse_times[min_idx].tt
        window_s = 10
        t_lo = ts.tt_jd(max(center_tt - window_s / 86400, rise_t.tt))
        t_hi = ts.tt_jd(min(center_tt + window_s / 86400, set_t.tt))
        refine_dur = (t_hi.tt - t_lo.tt) * 86400
        n_fine = max(20, int(refine_dur / 0.02))

        fine_times = ts.linspace(t_lo, t_hi, n_fine)
        iss_fine = (iss - observer).at(fine_times)
        iss_alt_f, iss_az_f, _ = iss_fine.altaz()

        sep_fine = _angular_sep_deg(
            iss_alt_f.degrees, iss_az_f.degrees,
            moon_alt.degrees, moon_az.degrees,
        )

        fine_min_idx = int(np.argmin(sep_fine))
        closest_sep = sep_fine[fine_min_idx]
        closest_time = fine_times[fine_min_idx]

        is_transit = closest_sep < moon_ang_radius

        # Transit duration: time within moon disk
        transit_duration_s = 0.0
        if is_transit:
            dt_sample = refine_dur / n_fine
            transit_duration_s = float(np.sum(sep_fine < moon_ang_radius)) * dt_sample

        # Moon illumination
        sun_astrometric = obs_pos.at(mid_t).observe(sun_body)
        elong = moon_astrometric.separation_from(sun_astrometric)
        moon_illum = (1 - math.cos(elong.radians)) / 2 * 100

        results.append({
            "time": closest_time,
            "min_sep": closest_sep,
            "moon_ang_radius": moon_ang_radius,
            "is_transit": is_transit,
            "transit_duration_s": transit_duration_s,
            "moon_alt": moon_alt.degrees,
            "moon_az": moon_az.degrees,
            "moon_illum": moon_illum,
            "iss_alt": iss_alt_f.degrees[fine_min_idx],
        })

    return results


def print_iss_transits(results, start_date, days, tz_offset):
    """Format and print ISS lunar transit search results."""
    tz = timezone(timedelta(hours=tz_offset))

    transits = [r for r in results if r["is_transit"]]
    near_misses = [r for r in results if not r["is_transit"]]

    if not results:
        print(f"\n  No ISS lunar transits or near misses found in {days}-day window.")
        print("  (This is normal — ISS lunar transits are rare for a fixed location.)")
        print("  Try extending the search with --days 60 or --days 90.")
        return

    if transits:
        print(f"\n  {'='*74}")
        print(f"  ISS LUNAR TRANSITS")
        print(f"  {'='*74}")
        for r in transits:
            dt = r["time"].utc_datetime().replace(tzinfo=timezone.utc).astimezone(tz)
            print(f"\n  >>> TRANSIT  {dt.strftime('%a %b %d  %H:%M:%S.%f')[:-5]} {TIMEZONE_NAME}")
            print(f"      Duration:  {r['transit_duration_s']:.2f}s")
            print(f"      Closest:   {r['min_sep']:.3f}° from center "
                  f"(moon radius: {r['moon_ang_radius']:.3f}°)")
            print(f"      Moon:      {r['moon_alt']:.1f}° alt, "
                  f"{r['moon_illum']:.0f}% illuminated")
            print(f"      ISS alt:   {r['iss_alt']:.1f}°")

    if near_misses:
        print(f"\n  {'─'*74}")
        print(f"  NEAR MISSES (ISS within {NEAR_MISS_DEG:.0f}° of Moon)")
        print(f"  {'─'*74}")
        near_misses.sort(key=lambda r: r["min_sep"])
        for r in near_misses:
            dt = r["time"].utc_datetime().replace(tzinfo=timezone.utc).astimezone(tz)
            label = "CLOSE" if r["min_sep"] < 1.0 else "near"
            print(f"\n  {label:>5}  {dt.strftime('%a %b %d  %H:%M:%S')} {TIMEZONE_NAME}"
                  f"  —  {r['min_sep']:.2f}° from center")
            print(f"         Moon: {r['moon_alt']:.1f}° alt, {r['moon_illum']:.0f}% illum"
                  f"  |  ISS: {r['iss_alt']:.1f}° alt")

    print(f"\n  {'─'*74}")
    print(f"  NOTE: ISS predictions degrade beyond ~1-2 weeks due to orbital maneuvers.")
    print(f"  Rerun closer to the date for precise timing. Transits last < 2 seconds")
    print(f"  — use video mode or a high-speed camera, not long-exposure stacking.")


# ──────────────────────────────────────────────────────────────────────
# Main
# ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Seestar S50 deep sky observation planner"
    )
    parser.add_argument(
        "--days", type=int, default=30,
        help="Number of days to plan ahead (default: 30)"
    )
    parser.add_argument(
        "--min-alt", type=float, default=35.0,
        help="Minimum altitude in degrees (default: 35)"
    )
    parser.add_argument(
        "--min-moon-sep", type=float, default=30.0,
        help="Minimum Moon separation in degrees (default: 30)"
    )
    parser.add_argument(
        "--top", type=int, default=10,
        help="Show top N targets per night (default: 10)"
    )
    parser.add_argument(
        "--type", type=str, default=None,
        help="Filter by type: emission, galaxy, globular, planetary, etc."
    )
    parser.add_argument(
        "--tonight", action="store_true",
        help="Show detailed plan for tonight only"
    )
    parser.add_argument(
        "--best-nights", action="store_true",
        help="For each DSO, show the single best night in the date range"
    )
    parser.add_argument(
        "--iss-transits", action="store_true",
        help="Search for ISS lunar transit opportunities (requires: pip install skyfield)"
    )
    args = parser.parse_args()

    location = EarthLocation(
        lat=LATITUDE * u.deg, lon=LONGITUDE * u.deg, height=ELEVATION * u.m
    )

    # Starting date: tonight (use local date)
    now_utc = datetime.now(timezone.utc)
    local_now = now_utc + timedelta(hours=TIMEZONE_OFFSET)
    # If it's before noon local, "tonight" means today's evening
    # If it's after noon, "tonight" means today's evening
    start_date = local_now.date()

    print("=" * 78)
    print(f"  SEESTAR S50 OBSERVATION PLANNER")
    print(f"  Location: Sunnyvale, CA ({LATITUDE:.2f}°N, {LONGITUDE:.2f}°W)")
    print(f"  Min altitude: {args.min_alt}°  |  Min moon separation: {args.min_moon_sep}°")
    print(f"  Date range: {start_date.strftime('%b %d')} — "
          f"{(start_date + timedelta(days=args.days-1)).strftime('%b %d, %Y')}")
    print(f"  Catalog: {len(DSO_CATALOG)} deep sky objects")
    print("=" * 78)

    if args.iss_transits:
        results = find_iss_lunar_transits(start_date, args.days)
        print_iss_transits(results, start_date, args.days, TIMEZONE_OFFSET)
        return

    # Pre-parse all catalog coordinates once (avoids re-parsing strings each night)
    targets = parse_catalog_coords(DSO_CATALOG)

    if args.best_nights:
        # ── MODE: Best night for each DSO ──
        print(f"\n{'OBJECT':<28} {'BEST NIGHT':<12} {'SCORE':>6} {'PEAK':>6} "
              f"{'WINDOW':<14} {'HRS':>4} {'MOON':>5} {'SEP':>5}")
        print("-" * 78)

        # Track best result per object (by name)
        best_by_name = {}
        for day_offset in range(args.days):
            night_date = start_date + timedelta(days=day_offset)
            date_utc = datetime(
                night_date.year, night_date.month, night_date.day,
                tzinfo=timezone.utc
            )
            dark_start, dark_end = find_darkness_window(
                location, date_utc, TIMEZONE_OFFSET
            )
            night_results = compute_night_batch(
                targets, DSO_CATALOG, location, dark_start, dark_end,
                args.min_alt, args.min_moon_sep, type_filter=args.type
            )
            for r in night_results:
                name = r["name"]
                if name not in best_by_name or r["score"] > best_by_name[name]["score"]:
                    r["night_date"] = night_date
                    best_by_name[name] = r

        results = sorted(best_by_name.values(), key=lambda r: r["score"], reverse=True)

        for r in results:
            label = score_label(r["score"])
            moon_str = f"{r['moon_illum']:3.0f}%"
            sep_str = f"{r['moon_sep']:4.1f}°"
            window = (f"{utc_to_local(r['window_start'], TIMEZONE_OFFSET)}-"
                      f"{utc_to_local(r['window_end'], TIMEZONE_OFFSET)}")
            display_name = f"{r['name']} {r['common']}"
            if len(display_name) > 27:
                display_name = display_name[:27]

            print(f"{display_name:<28} {r['night_date'].strftime('%b %d'):<12} "
                  f"{r['score']:>5.0f}  {r['peak_alt']:>5.1f}° "
                  f"{window:<14} {r['hours_above']:>3.1f} {moon_str:>5} {sep_str:>5}"
                  f"  {label}")

        return

    # ── MODE: Nightly plan (default or --tonight) ──
    n_days = 1 if args.tonight else args.days

    for day_offset in range(n_days):
        night_date = start_date + timedelta(days=day_offset)
        date_utc = datetime(
            night_date.year, night_date.month, night_date.day,
            tzinfo=timezone.utc
        )

        dark_start, dark_end = find_darkness_window(
            location, date_utc, TIMEZONE_OFFSET
        )

        if dark_start is None:
            print(f"\n  {night_date.strftime('%a %b %d')}: No astronomical darkness")
            continue

        dark_hours = (dark_end - dark_start).to(u.hour).value

        # Moon info at midnight local
        midnight_utc = Time(
            f"{night_date.strftime('%Y-%m-%d')}T07:00:00", scale="utc"
        )  # midnight PDT = 07:00 UTC
        moon_midnight = get_body("moon", midnight_utc, location)
        sun_midnight = get_sun(midnight_utc)
        elong = moon_midnight.separation(sun_midnight)
        moon_illum_midnight = (1 - math.cos(elong.rad)) / 2 * 100
        moon_altaz = moon_midnight.transform_to(
            AltAz(obstime=midnight_utc, location=location)
        )

        # Moon rise/set info
        moon_status = (f"alt {moon_altaz.alt.deg:+.0f}°" if moon_altaz.alt.deg > -5
                       else "below horizon")

        print(f"\n{'─' * 78}")
        print(f"  {night_date.strftime('%A, %b %d')}  |  "
              f"Dark: {utc_to_local(dark_start, TIMEZONE_OFFSET)}-"
              f"{utc_to_local(dark_end, TIMEZONE_OFFSET)} {TIMEZONE_NAME} "
              f"({dark_hours:.1f}h)  |  "
              f"Moon: {moon_illum_midnight:.0f}% {moon_status}")
        print(f"{'─' * 78}")

        # Compute visibility for all DSOs (batched)
        results = compute_night_batch(
            targets, DSO_CATALOG, location, dark_start, dark_end,
            args.min_alt, args.min_moon_sep, type_filter=args.type
        )

        if not results:
            print("  No targets above minimum altitude during darkness.")
            continue

        results.sort(key=lambda r: r["score"], reverse=True)
        shown = results[:args.top] if not args.tonight else results

        print(f"\n  {'OBJECT':<28} {'SCORE':>6} {'PEAK':>6} "
              f"{'WINDOW':<14} {'HRS':>4} {'MOON':>5} {'SEP':>5}")
        print(f"  {'-'*74}")

        for r in shown:
            label = score_label(r["score"])
            moon_str = f"{r['moon_illum']:3.0f}%"
            sep_str = f"{r['moon_sep']:4.1f}°"
            moon_warn = " ⚠ MOON" if r["moon_too_close"] else ""
            window = (f"{utc_to_local(r['window_start'], TIMEZONE_OFFSET)}-"
                      f"{utc_to_local(r['window_end'], TIMEZONE_OFFSET)}")

            display_name = f"{r['name']} {r['common']}"
            if len(display_name) > 27:
                display_name = display_name[:27]

            print(f"  {display_name:<28} {r['score']:>5.0f}  {r['peak_alt']:>5.1f}° "
                  f"{window:<14} {r['hours_above']:>3.1f} {moon_str:>5} {sep_str:>5}"
                  f"  {label}{moon_warn}")

        if args.tonight and results:
            print(f"\n  {'─' * 74}")
            print(f"  DETAILED NOTES")
            print(f"  {'─' * 74}")
            for r in shown:
                if r["score"] >= 40:
                    print(f"\n  {r['name']} ({r['common']}) — {r['type']}, "
                          f"mag {r['mag']}, {r['size']}' diameter")
                    print(f"    Peak: {r['peak_alt']:.1f}° at "
                          f"{utc_to_local(r['peak_time'], TIMEZONE_OFFSET)} {TIMEZONE_NAME}")
                    print(f"    Window: "
                          f"{utc_to_local(r['window_start'], TIMEZONE_OFFSET)}-"
                          f"{utc_to_local(r['window_end'], TIMEZONE_OFFSET)} "
                          f"({r['hours_above']:.1f}h above {args.min_alt}°)")
                    print(f"    Moon: {r['moon_illum']:.0f}% illuminated, "
                          f"{r['moon_sep']:.1f}° away"
                          f"{', below horizon' if r['moon_alt'] < 0 else ''}")
                    if r["notes"]:
                        print(f"    Tip: {r['notes']}")

    if not args.tonight and n_days > 1:
        print(f"\n{'=' * 78}")
        print(f"  TIP: Run with --tonight for detailed notes, or --best-nights")
        print(f"       to see the optimal night for each object.")
        print(f"       Filter by type with --type galaxy, --type emission, etc.")
        print(f"{'=' * 78}")


if __name__ == "__main__":
    main()
