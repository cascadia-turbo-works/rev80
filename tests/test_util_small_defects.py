"""Four small confirmed defects, each independently verified.

  - _pico_loader._drivers_dir() computed <repo>/src/drivers (one level short),
    so ensure_pico_dlls_loadable() silently returned False in development.
  - AMPLITUDE_SCALE.get() was called with two different fallbacks across five
    sites, so an unrecognised mode reconstructed a loaded trend 1.414x off
    relative to the live trend.
  - rev80/__init__.py does `from rev80.util import *` with no __all__ in
    util.py, re-exporting `np` into the rev80 namespace.
  - collector.py used the deprecated datetime.utcnow().
"""

import numpy as np
import pytest

import rev80
import rev80.util as util
from rev80._paths import project_path, resource_path
from rev80._pico_loader import _drivers_dir
from rev80.util import (
    AMPLITUDE_MODES,
    AMPLITUDE_SCALE,
    DEFAULT_AMPLITUDE_MODE,
    amplitude_scale,
)


# ---------------------------------------------------------------------------
# _pico_loader drivers path
# ---------------------------------------------------------------------------

class TestDriversDir:

    def test_resolves_to_repo_root_drivers(self):
        """The development path must be <repo root>/drivers, not src/rev80/drivers.

        drivers/ holds PicoSDK DLLs collected at the repo root by
        build/collect_pico_dlls.py and bundled by build/rev80.spec as a
        top-level directory — it is a build artifact, not package data.
        """
        expected = project_path('drivers')
        assert not str(expected).endswith('src/rev80/drivers')
        assert not str(expected).endswith('src/drivers')
        got = _drivers_dir()
        # drivers/ is checked into the repo, so this must resolve in a clone.
        assert got is not None, (
            f'drivers/ not found at {expected} — _drivers_dir() returned None, '
            f'which is the silent-failure mode this test exists to catch'
        )
        assert got == expected

    def test_agrees_with_paths_module(self):
        """_pico_loader must not re-derive what _paths already resolves."""
        assert _drivers_dir() == project_path('drivers')

    def test_does_not_resolve_through_package_data(self):
        """resource_path() is for package data and must NOT find drivers/.

        Narrowing resource_path() to the installed package is correct for
        logging.yaml and the icon font, but routing drivers/ through it
        reintroduces audit X-06 in a new shape: it resolves to a directory
        that never exists and the loader silently degrades to walking %PATH%.
        """
        assert not resource_path('drivers').is_dir()
        assert project_path('drivers') != resource_path('drivers')


# ---------------------------------------------------------------------------
# amplitude_scale — one fallback, defined once
# ---------------------------------------------------------------------------

class TestAmplitudeScale:

    @pytest.mark.parametrize('mode', AMPLITUDE_MODES)
    def test_known_modes_match_the_table(self, mode):
        assert amplitude_scale(mode) == AMPLITUDE_SCALE[mode]

    def test_rms_is_unity(self):
        assert amplitude_scale('RMS') == 1.0

    def test_zero_to_peak_is_sqrt2(self):
        assert amplitude_scale('0-P') == pytest.approx(np.sqrt(2))

    def test_peak_to_peak_is_two_sqrt2(self):
        assert amplitude_scale('P-P') == pytest.approx(2 * np.sqrt(2))

    @pytest.mark.parametrize('bad', ['Peak', '', 'rms', None, 0, object()])
    def test_unknown_modes_share_one_fallback(self, bad):
        """The whole point: every site must now agree on the same fallback."""
        assert amplitude_scale(bad) == AMPLITUDE_SCALE[DEFAULT_AMPLITUDE_MODE]

    def test_unknown_mode_is_logged(self, caplog):
        with caplog.at_level('WARNING'):
            amplitude_scale('Peak')
        assert any('Unknown amplitude mode' in r.message for r in caplog.records)

    def test_fallback_matches_the_or_default_used_at_call_sites(self):
        """Call sites normalise with `or '0-P'`; the fallback must agree."""
        assert DEFAULT_AMPLITUDE_MODE == '0-P'
        assert amplitude_scale('unrecognised') == amplitude_scale('0-P')

    def test_no_caller_uses_a_private_fallback(self):
        """No AMPLITUDE_SCALE.get() with its own default may survive in src/."""
        import pathlib
        root = pathlib.Path(rev80.__file__).parent
        offenders = [
            f'{p.name}:{i}'
            for p in root.rglob('*.py')
            if p.name != 'util.py'          # the definition site documents the old call
            for i, line in enumerate(p.read_text(errors='replace').splitlines(), 1)
            if 'AMPLITUDE_SCALE.get(' in line and not line.strip().startswith('#')
        ]
        assert offenders == [], (
            f'these sites bypass amplitude_scale() and can drift again: {offenders}'
        )


# ---------------------------------------------------------------------------
# util.__all__
# ---------------------------------------------------------------------------

class TestUtilAll:

    def test_all_is_defined(self):
        assert hasattr(util, '__all__')

    def test_every_name_exists(self):
        missing = [n for n in util.__all__ if not hasattr(util, n)]
        assert missing == [], f'__all__ names missing from util: {missing}'

    def test_numpy_is_not_re_exported(self):
        """`from rev80.util import *` used to leak `np` into the rev80 namespace."""
        assert not hasattr(rev80, 'np')

    @pytest.mark.parametrize('name', ['data_dir', 'SAVEDIR', 'amplitude_scale',
                                      'MONITOR_INTERVAL_PRESETS', 'UI_Elements'])
    def test_public_surface_still_reachable(self, name):
        """__all__ must not have narrowed the surface callers actually use.

        data_dir in particular is reached as rev80.data_dir() from six sites in
        gui.py/headless.py, and only arrives there via the star-import.
        """
        assert hasattr(rev80, name), f'rev80.{name} disappeared from the namespace'


# ---------------------------------------------------------------------------
# utcnow deprecation
# ---------------------------------------------------------------------------

def test_no_utcnow_calls_remain():
    """datetime.utcnow() is deprecated; no call may survive in src/."""
    import pathlib
    root = pathlib.Path(rev80.__file__).parent
    offenders = [
        f'{p.relative_to(root)}:{i}'
        for p in root.rglob('*.py')
        for i, line in enumerate(p.read_text(errors='replace').splitlines(), 1)
        if 'utcnow()' in line and not line.strip().startswith('#')
    ]
    assert offenders == [], f'deprecated utcnow() calls remain: {offenders}'
