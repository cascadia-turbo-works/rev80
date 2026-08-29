"""_build_anomaly_hook must work for every hook_type, in both front ends.

Bug: headless.py:162 and gui.py:2344 bound `period` only inside the
`if hook_type in ("rms","both")` branch, but both read it unconditionally in
the spectral branch (headless.py:182, gui.py:2368). A Spectral-only anomaly
config therefore raised UnboundLocalError.

In headless this fires AFTER collector.start_stream(), so the process dies
with the PicoScope still streaming and never closed — the scope is left in a
bad state that needs a physical replug.

The identical bug existed in both files because _build_anomaly_hook was
copy-pasted. These tests cover both copies so a fix to one cannot silently
leave the other broken.
"""

import pytest

from rev80.headless import _build_anomaly_hook as headless_build
from rev80.monitor.anomaly import (
    CompositeAnomalyHook,
    NullAnomalyHook,
    RmsThresholdHook,
    SpectralThresholdHook,
)
from rev80.sample import AcquisitionSettings
from rev80.util import DEFAULT_RMS_ALPHA, DEFAULT_SPEC_ALPHA

HOOK_TYPES = ['rms', 'spectral', 'both']


def _cfg():
    return AcquisitionSettings()


def _anom(hook_type, **over):
    d = {'enabled': True, 'hook_type': hook_type}
    d.update(over)
    return d


def _flatten(hook):
    """Return the list of leaf hooks, whatever wrapper came back."""
    if isinstance(hook, CompositeAnomalyHook):
        return list(hook._hooks)
    return [hook]


# ---------------------------------------------------------------------------
# headless
# ---------------------------------------------------------------------------

@pytest.mark.parametrize('hook_type', HOOK_TYPES)
def test_headless_builds_without_unbound_local(hook_type):
    """Every hook_type must build. 'spectral' used to raise UnboundLocalError."""
    hook = headless_build(_anom(hook_type), _cfg(), pre_buffer_s=60.0)
    assert not isinstance(hook, NullAnomalyHook)


@pytest.mark.parametrize('hook_type,expected', [
    ('rms', {RmsThresholdHook}),
    ('spectral', {SpectralThresholdHook}),
    ('both', {RmsThresholdHook, SpectralThresholdHook}),
])
def test_headless_builds_the_right_hooks(hook_type, expected):
    hook = headless_build(_anom(hook_type), _cfg(), pre_buffer_s=60.0)
    assert {type(h) for h in _flatten(hook)} == expected


@pytest.mark.parametrize('hook_type', HOOK_TYPES)
@pytest.mark.parametrize('spelling', [str.upper, str.title])
def test_headless_accepts_any_casing(hook_type, spelling):
    """Casing is normalised, so a capitalised config behaves identically."""
    a = headless_build(_anom(hook_type), _cfg(), pre_buffer_s=60.0)
    b = headless_build(_anom(spelling(hook_type)), _cfg(), pre_buffer_s=60.0)
    assert {type(h) for h in _flatten(a)} == {type(h) for h in _flatten(b)}


def test_headless_spectral_only_uses_period_for_alpha():
    """The spectral branch genuinely needs `period` — exercise that path."""
    cfg = _cfg()
    hook = headless_build(
        _anom('spectral', spec_ewma_time=300.0), cfg, pre_buffer_s=60.0
    )
    (spec,) = _flatten(hook)
    assert isinstance(spec, SpectralThresholdHook)
    # An EWMA time was supplied and period > 0, so alpha is computed, not the default.
    assert spec._alpha != DEFAULT_SPEC_ALPHA


def test_headless_disabled_returns_null_hook():
    hook = headless_build({'enabled': False}, _cfg(), pre_buffer_s=60.0)
    assert isinstance(hook, NullAnomalyHook)


# ---------------------------------------------------------------------------
# GUI — same function, second copy
# ---------------------------------------------------------------------------

class _FakeCollector:
    def __init__(self, config):
        self.config = config


def _gui_build(hook_type, widget_over=None):
    """Drive GUI._build_anomaly_hook with stubbed widget reads.

    _build_anomaly_hook reads every value through a local _get(tag, default)
    helper backed by DPG. Patching dpg lets the real method body run with no
    DPG context, which is the point: this is the second copy of the logic and
    it must be exercised, not assumed correct.
    """
    import rev80.gui as gui_module
    from rev80.gui import GUI

    ui = gui_module.ui
    values = {
        ui.MON_ANOM_ENABLED: True,
        ui.MON_ANOM_HOOK: hook_type,
    }
    values.update(widget_over or {})

    class _FakeDpg:
        @staticmethod
        def does_item_exist(tag):
            return tag in values

        @staticmethod
        def get_value(tag):
            return values.get(tag)

    app = object.__new__(GUI)
    app.collector = _FakeCollector(_cfg())

    real_dpg = gui_module.dpg
    gui_module.dpg = _FakeDpg
    try:
        return GUI._build_anomaly_hook(app, pre_buffer_s=60.0)
    finally:
        gui_module.dpg = real_dpg


@pytest.mark.parametrize('hook_type', HOOK_TYPES)
def test_gui_builds_without_unbound_local(hook_type):
    """Every hook_type must build. 'spectral' used to raise UnboundLocalError."""
    hook = _gui_build(hook_type)
    assert not isinstance(hook, NullAnomalyHook)


@pytest.mark.parametrize('hook_type,expected', [
    ('rms', {RmsThresholdHook}),
    ('spectral', {SpectralThresholdHook}),
    ('both', {RmsThresholdHook, SpectralThresholdHook}),
])
def test_gui_builds_the_right_hooks(hook_type, expected):
    assert {type(h) for h in _flatten(_gui_build(hook_type))} == expected


@pytest.mark.parametrize('hook_type', HOOK_TYPES)
def test_gui_accepts_gui_combo_labels(hook_type):
    """The combo hands back 'RMS'/'Spectral'/'Both'; both spellings must agree."""
    from rev80.util import hook_type_label
    a = _gui_build(hook_type)
    b = _gui_build(hook_type_label(hook_type))
    assert {type(h) for h in _flatten(a)} == {type(h) for h in _flatten(b)}


# ---------------------------------------------------------------------------
# The two copies must agree — these are the four documented drifts
# ---------------------------------------------------------------------------

@pytest.mark.parametrize('hook_type', HOOK_TYPES)
def test_both_front_ends_build_the_same_hook_types(hook_type):
    gui_types = {type(h) for h in _flatten(_gui_build(hook_type))}
    headless_types = {type(h) for h in _flatten(
        headless_build(_anom(hook_type), _cfg(), pre_buffer_s=60.0))}
    assert gui_types == headless_types


def test_warmup_default_agrees_between_front_ends():
    """Drift: GUI defaulted warmup to 30, headless to 10 (config.py seeds 10)."""
    import rev80.config as cfg_mod
    seeded = cfg_mod._BUILTIN_ACQ['monitor']['anomaly']['warmup']

    (gui_rms,) = _flatten(_gui_build('rms'))
    (hl_rms,) = _flatten(headless_build(_anom('rms'), _cfg(), pre_buffer_s=60.0))

    assert gui_rms._min_samples == hl_rms._min_samples
    assert gui_rms._min_samples == seeded


def test_spec_n_default_agrees_between_front_ends():
    """Drift: GUI defaulted spec_n to 3, headless to 10 (config.py seeds 10)."""
    import rev80.config as cfg_mod
    seeded = cfg_mod._BUILTIN_ACQ['monitor']['anomaly']['spec_n']

    (gui_spec,) = _flatten(_gui_build('spectral'))
    (hl_spec,) = _flatten(headless_build(_anom('spectral'), _cfg(), pre_buffer_s=60.0))

    assert gui_spec._consecutive_n == hl_spec._consecutive_n
    assert gui_spec._consecutive_n == seeded


def test_alpha_fallback_constants_are_shared():
    """Drift: the EWMA-alpha fallbacks were hardcoded separately in each copy."""
    import rev80.config as cfg_mod
    anom = cfg_mod._BUILTIN_ACQ['monitor']['anomaly']
    assert anom['rms_alpha'] == DEFAULT_RMS_ALPHA
    assert anom['spec_alpha'] == DEFAULT_SPEC_ALPHA
