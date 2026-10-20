"""_build_anomaly_hook builds every hook_type, in both front ends.

gui.py and headless.py each hold a copy of _build_anomaly_hook, so these tests
run both copies and check that their defaults agree. In headless the hook is
built after the stream starts, so an exception there leaves the scope open.
"""

import pytest

from rev80.headless import _build_anomaly_hook as headless_build
from rev80.monitor.anomaly import (
    CompositeAnomalyHook,
    FixedThresholdHook,
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
    """Every hook_type builds a hook, including 'spectral' alone."""
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
    """The spectral-only branch computes alpha from the frame period."""
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
    """Run GUI._build_anomaly_hook with a stub dpg, so no DPG context is needed.

    The stub answers the method's widget reads from ``values``.
    """
    pytest.importorskip("dearpygui")
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
    """Every hook_type builds a hook, including 'spectral' alone."""
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
# The two copies must agree
# ---------------------------------------------------------------------------

@pytest.mark.parametrize('hook_type', HOOK_TYPES)
def test_both_front_ends_build_the_same_hook_types(hook_type):
    gui_types = {type(h) for h in _flatten(_gui_build(hook_type))}
    headless_types = {type(h) for h in _flatten(
        headless_build(_anom(hook_type), _cfg(), pre_buffer_s=60.0))}
    assert gui_types == headless_types


def test_warmup_default_agrees_between_front_ends():
    """Both copies default warmup to the value that config.py seeds."""
    import rev80.config as cfg_mod
    seeded = cfg_mod._BUILTIN_ACQ['monitor']['anomaly']['warmup']

    (gui_rms,) = _flatten(_gui_build('rms'))
    (hl_rms,) = _flatten(headless_build(_anom('rms'), _cfg(), pre_buffer_s=60.0))

    assert gui_rms._min_samples == hl_rms._min_samples
    assert gui_rms._min_samples == seeded


def test_spec_n_default_agrees_between_front_ends():
    """Both copies default spec_n to the value that config.py seeds."""
    import rev80.config as cfg_mod
    seeded = cfg_mod._BUILTIN_ACQ['monitor']['anomaly']['spec_n']

    (gui_spec,) = _flatten(_gui_build('spectral'))
    (hl_spec,) = _flatten(headless_build(_anom('spectral'), _cfg(), pre_buffer_s=60.0))

    assert gui_spec._consecutive_n == hl_spec._consecutive_n
    assert gui_spec._consecutive_n == seeded


def test_alpha_fallback_constants_are_shared():
    """The seeded EWMA alpha values are the shared util constants."""
    import rev80.config as cfg_mod
    anom = cfg_mod._BUILTIN_ACQ['monitor']['anomaly']
    assert anom['rms_alpha'] == DEFAULT_RMS_ALPHA
    assert anom['spec_alpha'] == DEFAULT_SPEC_ALPHA


def _seeded(key):
    import rev80.config as cfg_mod
    return cfg_mod._BUILTIN_ACQ['monitor']['anomaly'][key]


def test_hook_view_defaults_agree_between_front_ends():
    """No view keys: both copies read the record view (the seed is '')."""
    (gui_rms,) = _flatten(_gui_build('rms'))
    (hl_rms,) = _flatten(headless_build(_anom('rms'), _cfg(), pre_buffer_s=60.0))
    assert (gui_rms._unit, gui_rms._mode) == (hl_rms._unit, hl_rms._mode)
    assert (gui_rms._unit, gui_rms._mode) == (_seeded('rms_unit'), _seeded('rms_amplitude_mode'))
    assert gui_rms._unit == ''


def _fixed_of(hook):
    (fixed,) = [h for h in _flatten(hook) if isinstance(h, FixedThresholdHook)]
    return fixed


def test_fixed_defaults_agree_between_front_ends():
    """Upper limit on, no mode and no fixed_s: both copies fire on one frame."""
    import rev80.gui as gui_module
    ui = gui_module.ui
    gui = _fixed_of(_gui_build('rms', {ui.MON_ANOM_FIXED_UPPER_ENABLED: True}))
    hl = _fixed_of(headless_build(_anom('rms', fixed_upper_enabled=True), _cfg(),
                                  pre_buffer_s=60.0))
    assert (gui._upper_mode, gui._lower_mode) == (hl._upper_mode, hl._lower_mode) == ('', '')
    assert gui._sustain_frames == hl._sustain_frames == 1
    assert _seeded('fixed_s') == 0.0


def test_both_front_ends_pass_the_view_keys():
    import rev80.gui as gui_module
    ui = gui_module.ui
    gui = _flatten(_gui_build('rms', {
        ui.MON_ANOM_RMS_UNIT: 'g', ui.MON_ANOM_RMS_MODE: 'P-P',
        ui.MON_ANOM_FIXED_UPPER_ENABLED: True, ui.MON_ANOM_FIXED_UPPER_MODE: 'RMS',
        ui.MON_ANOM_FIXED_S: 3.0}))
    hl = _flatten(headless_build(_anom(
        'rms', rms_unit='g', rms_amplitude_mode='P-P', fixed_upper_enabled=True,
        fixed_upper_mode='RMS', fixed_s=3.0), _cfg(), pre_buffer_s=60.0))
    for leaves in (gui, hl):
        rms = next(h for h in leaves if isinstance(h, RmsThresholdHook))
        (fixed,) = [h for h in leaves if isinstance(h, FixedThresholdHook)]
        assert (rms._unit, rms._mode) == ('g', 'P-P')
        assert fixed._upper_mode == 'RMS'
        assert fixed._sustain_frames == round(3.0 / _cfg().acquisition_period) + 1


def test_frames_for_seconds():
    from rev80.monitor.anomaly import frames_for_seconds
    assert frames_for_seconds(0.0, 0.5) == 1
    assert frames_for_seconds(3.0, 0.5) == 7
    assert frames_for_seconds(3.0, 0.0) == 1
