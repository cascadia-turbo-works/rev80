"""Monitor config values round-trip through config.py, the GUI and headless.

Each seeded default is a value the GUI widget can show. A populate-then-save
cycle writes back the value it read, including a hook type the GUI cannot show.
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
    """The shipped interval_s default is a member of the GUI interval combo.

    If it were not, the combo would show a fallback label ('1 h') and a save
    would write 3600 s over the configured 600 s.
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
    pytest.importorskip("dearpygui")
    from rev80.gui import GUI
    stub = SimpleNamespace(_stored_hook_type=stored_hook_type)
    return GUI._hook_type_to_save(stub, widget_value)


def test_gui_combo_items_match_labels():
    """Each GUI combo item round-trips through the label helpers.

    The GUI offers only GUI_ANOMALY_HOOK_TYPES (the spectral hook is tracked as
    R39 in doc/PROGRESS.md). Every canonical type keeps a label for headless.
    """
    combo_items = [ANOMALY_HOOK_LABELS[k] for k in GUI_ANOMALY_HOOK_TYPES]
    for item in combo_items:
        assert hook_type_label(canonical_hook_type(item)) == item
    for canonical, label in ANOMALY_HOOK_LABELS.items():
        assert canonical_hook_type(label) == canonical


@pytest.mark.parametrize('stored', sorted(ANOMALY_HOOK_LABELS))
def test_gui_hook_type_clamps_to_something_the_combo_lists(stored):
    """gui_hook_type() returns only values that the combo lists.

    A DPG combo set to an absent item falls back without a message.
    """
    assert gui_hook_type(stored) in GUI_ANOMALY_HOOK_TYPES


@pytest.mark.parametrize('stored', sorted(ANOMALY_HOOK_LABELS))
def test_opening_the_gui_dialog_does_not_rewrite_a_headless_hook_type(stored):
    """Populate-then-save keeps a hook type that the GUI cannot show.

    The GUI shows 'spectral'/'both' as 'rms'. It does not write 'rms' back.
    """
    shown_label = hook_type_label(gui_hook_type(stored))
    saved = _save_hook_type(stored_hook_type=stored, widget_value=shown_label)
    assert saved == stored


def test_an_explicit_pick_beats_the_preserved_value():
    """A widget value other than the clamped stand-in is a user selection and wins.

    'both' is stored and the widget reads 'Spectral', which 'both' does not
    clamp to.
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
    """600 s maps to 600 s, not to 3600 s."""
    assert nearest_interval_preset(600) != 3600


@pytest.mark.parametrize('bad', [None, 'nonsense'])
def test_nearest_preset_handles_garbage(bad):
    assert nearest_interval_preset(bad) in MONITOR_INTERVAL_PRESETS


# ---------------------------------------------------------------------------
# Full round trip: builtin defaults -> GUI populate -> GUI save -> unchanged
# ---------------------------------------------------------------------------

def test_defaults_round_trip_through_gui_widget_values():
    """A populate-then-save cycle keeps the seeded interval_s and hook_type.

    The steps copy _populate_monitor_tab and _save_monitor_config for these
    two fields, without a DPG context.
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
    """The seeded hook_type selects at least one hook group.

    If it matched no group, no hook would be built and anomaly detection
    would be off on a fresh install.
    """
    hook = canonical_hook_type(cfg._BUILTIN_ACQ['monitor']['anomaly']['hook_type'])
    rms_shown = hook in ('rms', 'both')
    spec_shown = hook in ('spectral', 'both')
    assert rms_shown or spec_shown, 'fresh install shows no anomaly hook group at all'
