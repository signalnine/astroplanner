"""Tests for explicit handling of M40 (double star) and M73 (asterism) types.

These two Messier objects are not real DSOs and previously fell through to
default fallbacks in both LP_FILTER_AUTO (False) and score_observation's
moon_sensitivity dict (0.7). The fallback values were not deliberate. These
tests pin down explicit values so the behavior is documented.

Star-like objects should:
  - get LP_FILTER_AUTO = False (no narrowband emission to isolate)
  - get a low moon_sensitivity (~0.2, like open clusters) since stellar
    point sources are far less sensitive to moon glare than diffuse nebulae.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from astroplanner import LP_FILTER_AUTO, score_observation


def test_lp_filter_auto_has_explicit_double_star_entry():
    assert "double star" in LP_FILTER_AUTO
    assert LP_FILTER_AUTO["double star"] is False


def test_lp_filter_auto_has_explicit_asterism_entry():
    assert "asterism" in LP_FILTER_AUTO
    assert LP_FILTER_AUTO["asterism"] is False


def _score_with_full_moon_close_by(obj_type):
    # Holding everything else constant, only obj_type drives differences via
    # the moon_sensitivity lookup. Use full moon and short separation so the
    # sensitivity multiplier dominates.
    return score_observation(
        peak_alt=60,
        moon_illum_pct=100,
        moon_sep_deg=80,
        hours_above_min=4,
        difficulty=5,
        obj_type=obj_type,
    )


def test_double_star_uses_low_moon_sensitivity_like_open_cluster():
    # If sensitivity is set to 0.2 (matching open cluster), the score must
    # equal the open-cluster score for identical inputs. The default
    # fallback (0.7) would produce a meaningfully lower score.
    assert _score_with_full_moon_close_by("double star") == _score_with_full_moon_close_by("open cluster")


def test_asterism_uses_low_moon_sensitivity_like_open_cluster():
    assert _score_with_full_moon_close_by("asterism") == _score_with_full_moon_close_by("open cluster")


def test_double_star_not_using_default_fallback():
    # The default fallback is 0.7. An unknown type would receive that value
    # and produce a different (lower) score. This guards against the type
    # being silently absent from the dict.
    explicit = _score_with_full_moon_close_by("double star")
    fallback = _score_with_full_moon_close_by("definitely_not_a_real_type")
    assert explicit != fallback
    assert explicit > fallback


def test_asterism_not_using_default_fallback():
    explicit = _score_with_full_moon_close_by("asterism")
    fallback = _score_with_full_moon_close_by("definitely_not_a_real_type")
    assert explicit != fallback
    assert explicit > fallback
