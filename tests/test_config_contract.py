"""The config contract between config.py, the GUI and headless must round-trip.

config.py seeds defaults that the GUI then silently rewrote:

  - config.py:83 seeds hook_type: 'rms' (lowercase). The GUI combo items are
    ["RMS", "Spectral", "Both"] and _build_anomaly_hook / _on_anom_config_change
    compared against the capitalised forms with no normalisation, while
    headless.py did .lower(). Opening Config->Monitor once on a fresh install
    therefore hid BOTH hook groups, built ZERO anomaly hooks, and silently
    disabled anomaly detection.

  - config.py:74 seeds interval_s: 600, which was not a member of
    MONITOR_INTERVAL_PRESETS. The widget fell back to the '1 h' label and
    _save_monitor_config wrote 3600.0 back — silently changing a user's
    10-minute logging interval to one hour.
"""

from types import SimpleNamespace
import pytest

import rev80.config as cfg
from rev80.util import (
    ANOMALY_HOOK_LABELS,
    MONITOR_INTERVAL_PRESETS,
    GUI_ANOMALY_HOOK_TYPES,
    canonical_hook_type,
    gui_hook_type,
    hook_type_label,
    nearest_interval_preset,
)


# ---------------------------------------------------------------------------
# Every shipped default must be representable by the widget that edits it
# ---------------------------------------------------------------------------

def test_seeded_interval_is_a_preset_member():
    """The shipped interval_s default must be selectable in the GUI combo.

    When it was not, the combo silently fell back to '1 h' and saving
    persisted 3600 over the user's 600.
    """
    seeded = cfg._BUILTIN_ACQ['monitor']['interval_s']
    assert int(seeded) in MONITOR_INTERVAL_PRESETS, (
        f'seeded interval_s={seeded} is not a MONITOR_INTERVAL_PRESETS key, so '
        f'the GUI cannot represent it and will rewrite it on save'
    )


def test_seeded_hook_type_is_canonical():
    """The shipped hook_type default must survive normalisation unchanged."""
    seeded = cfg._BUILTIN_ACQ['monitor']['anomaly']['hook_type']
    assert seeded in ANOMALY_HOOK_LABELS
    assert canonical_hook_type(seeded) == seeded


# ---------------------------------------------------------------------------
# hook_type normalisation
# ---------------------------------------------------------------------------

@pytest.mark.parametrize('raw,expected', [
    ('rms', 'rms'), ('RMS', 'rms'), ('Rms', 'rms'), ('  rms  ', 'rms'),
    ('spectral', 'spectral'), ('Spectral', 'spectral'), ('SPECTRAL', 'spectral'),
    ('both', 'both'), ('Both', 'both'), ('BOTH', 'both'),
])
def test_canonical_hook_type_normalises_case(raw, expected):
    assert canonical_hook_type(raw) == expected


@pytest.mark.parametrize('raw', ['', 'nonsense', None, 123])
def test_canonical_hook_type_falls_back_to_rms(raw):
    assert canonical_hook_type(raw) == 'rms'


@pytest.mark.parametrize('canonical,label', list(ANOMALY_HOOK_LABELS.items()))
def test_label_round_trips_through_canonical(canonical, label):
    """GUI label -> canonical -> label must be stable in both directions."""
    assert hook_type_label(canonical) == label
    assert canonical_hook_type(label) == canonical


def _save_hook_type(stored_hook_type, widget_value):
    """Call GUI._hook_type_to_save without standing up a DPG context.

    It touches only self._stored_hook_type, so a stub carrying that attribute
    exercises the shipped method rather than a paraphrase of it.
    """
    from rev80.gui import GUI
    stub = SimpleNamespace(_stored_hook_type=stored_hook_type)
    return GUI._hook_type_to_save(stub, widget_value)


def test_gui_combo_items_match_labels():
    """The GUI combo items are exactly the display labels of the offered subset.

    The GUI no longer offers every hook type -- 'spectral'/'both' were unwired
    from the panel (see GUI_ANOMALY_HOOK_TYPES and R39) -- but every item it
    does show must still round-trip through the label helpers, and every
    canonical type must still have a label so headless configs stay readable.
    """
    combo_items = [ANOMALY_HOOK_LABELS[k] for k in GUI_ANOMALY_HOOK_TYPES]
    for item in combo_items:
        assert hook_type_label(canonical_hook_type(item)) == item
    for canonical, label in ANOMALY_HOOK_LABELS.items():
        assert canonical_hook_type(label) == canonical


@pytest.mark.parametrize('stored', sorted(ANOMALY_HOOK_LABELS))
def test_gui_hook_type_clamps_to_something_the_combo_lists(stored):
    """Never hand the combo a value outside its own item list.

    Setting a DPG combo to an absent item is the S-07 failure mode: it falls
    back silently and the user never learns the setting was not applied.
    """
    assert gui_hook_type(stored) in GUI_ANOMALY_HOOK_TYPES


@pytest.mark.parametrize('stored', sorted(ANOMALY_HOOK_LABELS))
def test_opening_the_gui_dialog_does_not_rewrite_a_headless_hook_type(stored):
    """Populate-then-save must preserve a hook type the GUI cannot display.

    Headless still offers 'spectral'/'both'. Merely opening the monitor dialog
    in the GUI -- which clamps them to 'rms' for display -- must not write that
    stand-in back over the user's configuration.
    """
    shown_label = hook_type_label(gui_hook_type(stored))
    saved = _save_hook_type(stored_hook_type=stored, widget_value=shown_label)
    assert saved == stored


def test_an_explicit_pick_beats_the_preserved_value():
    """Preservation must only cover the untouched stand-in, not pin the field.

    Constructed so the two rules disagree: 'both' is stored, the widget reads
    'Spectral'. That is not the value 'both' clamps to, so it can only have
    come from a deliberate selection and must win.
    """
    assert _save_hook_type(stored_hook_type='both', widget_value='Spectral') == 'spectral'
    # And a type the GUI does offer is always written straight through.
    assert _save_hook_type(stored_hook_type='rms', widget_value='RMS') == 'rms'


# ---------------------------------------------------------------------------
# interval preset fallback
# ---------------------------------------------------------------------------

@pytest.mark.parametrize('key', list(MONITOR_INTERVAL_PRESETS))
def test_preset_members_map_to_themselves(key):
    assert nearest_interval_preset(key) == key


@pytest.mark.parametrize('seconds,expected', [
    (601, 600),      # just off 10 min -> 10 min, not 1 h
    (700, 600),
    (1000, 900),
    (10, 5),
    (100000, 86400),
])
def test_nearest_preset_picks_the_closest(seconds, expected):
    assert nearest_interval_preset(seconds) == expected


def test_nearest_preset_never_jumps_to_an_hour_for_ten_minutes():
    """The specific regression: 600 must not become 3600."""
    assert nearest_interval_preset(600) != 3600


@pytest.mark.parametrize('bad', [None, 'nonsense'])
def test_nearest_preset_handles_garbage(bad):
    assert nearest_interval_preset(bad) in MONITOR_INTERVAL_PRESETS


# ---------------------------------------------------------------------------
# Full round trip: builtin defaults -> GUI populate -> GUI save -> unchanged
# ---------------------------------------------------------------------------

def test_defaults_round_trip_through_gui_widget_values():
    """Simulate populate-then-save over the monitor config and assert stability.

    This mirrors what _populate_monitor_config / _save_monitor_config do with
    the two fields that were being rewritten, without needing a DPG context.
    """
    monitor = cfg._BUILTIN_ACQ['monitor']
    interval_s = monitor['interval_s']
    hook_type = monitor['anomaly']['hook_type']

    # --- populate: value -> widget label (what the combo displays)
    interval_label = MONITOR_INTERVAL_PRESETS.get(
        int(interval_s),
        MONITOR_INTERVAL_PRESETS[nearest_interval_preset(interval_s)],
    )
    hook_label = hook_type_label(hook_type)

    # --- save: widget label -> value written back to acquisition.yaml
    saved_interval = next(
        (k for k, v in MONITOR_INTERVAL_PRESETS.items() if v == interval_label),
        3600,
    )
    saved_hook = canonical_hook_type(hook_label)

    assert saved_interval == interval_s, (
        f'interval_s {interval_s} was rewritten to {saved_interval} by a '
        f'populate/save cycle that changed nothing'
    )
    assert saved_hook == hook_type, (
        f'hook_type {hook_type!r} was rewritten to {saved_hook!r}'
    )


def test_seeded_hook_type_selects_a_hook_group():
    """A fresh install must show at least one hook group, not zero.

    With no normalisation, the seeded 'rms' matched neither ('RMS','Both') nor
    ('Spectral','Both'), so both groups were hidden and no hooks were built.
    """
    hook = canonical_hook_type(cfg._BUILTIN_ACQ['monitor']['anomaly']['hook_type'])
    rms_shown = hook in ('rms', 'both')
    spec_shown = hook in ('spectral', 'both')
    assert rms_shown or spec_shown, 'fresh install shows no anomaly hook group at all'
