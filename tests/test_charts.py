"""The chart model: specs, validation, the default layout and charts.yaml.

`rev80.charts` has no dearpygui import, so the converter and headless can
use it. The chart sets the unit and mode of every series on it.
"""

import logging

import pytest
import yaml

from rev80 import charts
from rev80.charts import ChartSet, ChartSpec


def _spec(**over):
    d = dict(chart_id='c1', chart_type='spectrum', name='Spectrum',
             channels=(0, 1), unit='in/s', amplitude_mode='0-P')
    d.update(over)
    return ChartSpec(**d)


# --- Model -------------------------------------------------------------------

def test_spec_is_immutable_and_channels_are_a_tuple():
    s = _spec(channels=[0, 1])
    assert s.channels == (0, 1)
    with pytest.raises(AttributeError):
        s.name = 'x'


def test_round_trip_of_every_chart_type():
    cs = ChartSet((
        _spec(chart_id='w', chart_type='waveform', unit='g', amplitude_mode=''),
        _spec(chart_id='s', averaging=True, n_averages=4),
        _spec(chart_id='t', chart_type='trend', show_rpm=True, tach_channel=3),
        _spec(chart_id='e', chart_type='envelope', unit='g'),
        _spec(chart_id='x', chart_type='xy', channels=(1, 0), unit='mm', amplitude_mode=''),
    ))
    again = ChartSet.from_dict(cs.to_dict())
    assert again == cs
    # The dict is plain data: YAML gives it back unchanged.
    assert ChartSet.from_dict(yaml.safe_load(yaml.safe_dump(cs.to_dict()))) == cs


def test_a_bad_entry_is_skipped_and_logged(caplog):
    good = _spec().to_dict()
    d = {'version': 1, 'charts': [
        good,
        {**good, 'chart_id': 'c2', 'chart_type': 'polar'},     # unknown type
        {**good, 'chart_id': 'c3', 'channels': 'all'},         # not a list
        {**good},                                              # duplicate id
        'not a mapping',
        {**good, 'chart_id': 'c4', 'n_averages': 0},           # clamped, kept
    ]}
    with caplog.at_level(logging.WARNING, logger='rev80.charts'):
        cs = ChartSet.from_dict(d)
    assert [c.chart_id for c in cs.charts] == ['c1', 'c4']
    assert cs.chart('c4').n_averages == 1
    assert sum('skipped' in r.getMessage() for r in caplog.records) == 4


def test_from_dict_of_garbage_is_an_empty_set(caplog):
    with caplog.at_level(logging.WARNING, logger='rev80.charts'):
        assert ChartSet.from_dict(None).charts == ()
        assert ChartSet.from_dict({'charts': 5}).charts == ()


def test_edits_return_a_new_set():
    cs = ChartSet((_spec(),))
    cid = cs.new_chart_id()
    added = cs.with_chart(_spec(chart_id=cid, chart_type='waveform', amplitude_mode=''))
    assert len(cs.charts) == 1 and len(added.charts) == 2
    renamed = added.replace_chart(cs.chart('c1').evolve(name='Velocity'))
    assert renamed.chart('c1').name == 'Velocity'
    assert added.chart('c1').name == 'Spectrum'
    assert [c.chart_id for c in renamed.without('c1').charts] == [cid]
    assert cid not in {'c1'} and cid == added.charts[1].chart_id


def test_new_chart_ids_are_unique():
    cs = ChartSet(())
    ids = []
    for _ in range(5):
        cid = cs.new_chart_id()
        ids.append(cid)
        cs = cs.with_chart(_spec(chart_id=cid))
    assert len(set(ids)) == 5
    # An id is never reused after a remove.
    cs = cs.without(ids[-1])
    assert cs.new_chart_id() not in ids[:-1]


# --- Units -------------------------------------------------------------------

def test_unit_reachable_rules():
    r = charts.unit_reachable
    assert r(None, 'mV') and not r(None, 'g')                     # no sensor: mV only
    assert r('g', 'g') and r('g', 'in/s') and r('g', 'mil')        # two integrations
    assert not r('g', 'mV')                                        # mV is not an EU
    assert r('mV', 'mV')                                           # Source EU mV
    assert r('mil', 'g')                                           # two differentiations
    assert not r('g', 'furlongs')


def test_envelope_units_are_the_same_quantity_only():
    r = charts.unit_reachable
    assert r('g', 'mm/s2', 'envelope') and r('g', 'g', 'envelope')
    assert not r('g', 'in/s', 'envelope')
    assert r(None, 'mV', 'envelope')


def test_allowed_units_is_the_intersection_over_the_checked_channels():
    assert charts.allowed_units('spectrum', ['g', 'g']) == [
        'g', 'mm/s2', 'in/s2', 'mil/s2', 'mm/s', 'in/s', 'mil/s', 'mm', 'in', 'mil']
    assert charts.allowed_units('spectrum', ['mm']) == [
        'g', 'mm/s2', 'in/s2', 'mil/s2', 'mm/s', 'in/s', 'mil/s', 'mm', 'in', 'mil']
    assert charts.allowed_units('spectrum', [None]) == ['mV']
    assert charts.allowed_units('spectrum', [None, 'g']) == []
    assert charts.allowed_units('envelope', ['g']) == ['g', 'mm/s2', 'in/s2', 'mil/s2']
    assert charts.allowed_units('spectrum', []) == list(charts.UNITS)


def test_modes_for_each_chart_type():
    assert charts.modes_for('spectrum') == ('RMS', '0-P', 'P-P')
    assert charts.modes_for('trend') == ('RMS', '0-P', 'P-P')
    assert charts.modes_for('envelope') == ('RMS', '0-P', 'P-P')
    assert charts.modes_for('waveform') == ('',)
    assert charts.modes_for('xy') == ('',)


def test_a_tachometer_channel_is_never_selectable():
    roles = {0: 'vibration', 2: 'tachometer'}
    eus = {0: 'g', 2: None}
    ok, why = charts.channel_selectable(_spec(), 2, roles, eus)
    assert not ok and 'tachometer' in why
    assert charts.channel_selectable(_spec(), 0, roles, eus) == (True, '')


def test_a_channel_that_cannot_reach_the_unit_is_not_selectable():
    ok, why = charts.channel_selectable(_spec(unit='in/s'), 1, {1: 'vibration'}, {1: None})
    assert not ok and 'no sensor' in why


# --- Problems shown on the chart tab -----------------------------------------

def test_problems_of_a_chart():
    roles = {0: 'vibration', 1: 'vibration', 2: 'tachometer'}
    eus = {0: 'g', 1: None, 2: None}
    assert charts.problems(_spec(channels=(0,)), roles, eus) == []
    assert charts.problems(_spec(channels=()), roles, eus) == ['no channel selected']
    p = charts.problems(_spec(channels=(0, 1)), roles, eus)
    assert p == ['ch1: no sensor, cannot show in/s']
    assert charts.problems(_spec(channels=(0, 2)), roles, eus) == [
        'ch2: a tachometer channel; use it as the shaft speed of a trend']
    assert charts.problems(_spec(channels=(5,)), roles, eus) == ['ch5: not present']
    xy = _spec(chart_type='xy', channels=(0,), unit='g', amplitude_mode='')
    assert charts.problems(xy, roles, eus) == ['XY needs two different channels']
    assert charts.problems(xy.evolve(channels=(0, 0)), roles, eus) == [
        'XY needs two different channels']


def test_a_trend_tach_channel_must_be_a_tachometer():
    roles = {0: 'vibration', 2: 'tachometer'}
    eus = {0: 'g', 2: None}
    t = _spec(chart_type='trend', channels=(0,), show_rpm=True, tach_channel=0)
    assert charts.problems(t, roles, eus) == ['ch0: not a tachometer channel']
    assert charts.problems(t.evolve(tach_channel=2), roles, eus) == []


# --- Default layout ----------------------------------------------------------

def test_default_layout_is_a_waveform_and_a_spectrum_of_all_vibration_channels():
    cs = charts.default_layout([0, 1, 3], lambda ch: ('in/s', 'P-P'))
    assert [c.chart_type for c in cs.charts] == ['waveform', 'spectrum']
    assert all(c.channels == (0, 1, 3) for c in cs.charts)
    wf, sp = cs.charts
    assert (wf.unit, wf.amplitude_mode) == ('in/s', '')
    assert (sp.unit, sp.amplitude_mode) == ('in/s', 'P-P')
    assert wf.chart_id != sp.chart_id
    assert not sp.averaging


def test_default_layout_with_no_channel():
    cs = charts.default_layout([], lambda ch: ('in/s', '0-P'))
    assert [(c.chart_type, c.unit) for c in cs.charts] == [('waveform', 'mV'), ('spectrum', 'mV')]


# --- charts.yaml -------------------------------------------------------------

def test_save_and_load(tmp_path):
    path = tmp_path / 'charts.yaml'
    cs = charts.default_layout([0], lambda ch: ('g', 'RMS'))
    charts.save_chart_set(path, cs)
    assert charts.load_chart_set(path, lambda: ChartSet(())) == (cs, True)


def test_a_missing_file_gives_the_default(tmp_path):
    default = charts.default_layout([0], lambda ch: ('g', 'RMS'))
    assert charts.load_chart_set(tmp_path / 'none.yaml', lambda: default) == (default, False)


@pytest.mark.parametrize('content', ['charts: [', '- just a list\n', '\x00\x01'])
def test_a_bad_file_gives_the_default_and_is_not_overwritten(tmp_path, caplog, content):
    path = tmp_path / 'charts.yaml'
    path.write_text(content)
    default = charts.default_layout([0], lambda ch: ('g', 'RMS'))
    with caplog.at_level(logging.WARNING, logger='rev80.charts'):
        cs, ok = charts.load_chart_set(path, lambda: default)
    assert (cs, ok) == (default, False)
    assert path.read_text() == content
    assert any('charts.yaml' in r.getMessage() for r in caplog.records)


def test_a_file_with_no_valid_chart_gives_the_default(tmp_path):
    path = tmp_path / 'charts.yaml'
    path.write_text(yaml.safe_dump({'version': 1, 'charts': [{'chart_type': 'polar'}]}))
    default = charts.default_layout([0], lambda ch: ('g', 'RMS'))
    assert charts.load_chart_set(path, lambda: default) == (default, False)


def test_charts_config_path_is_in_the_config_dir(monkeypatch, tmp_path):
    import rev80.config as cfg
    monkeypatch.setenv('XDG_CONFIG_HOME', str(tmp_path))
    monkeypatch.setattr(cfg.sys, 'platform', 'linux')
    assert cfg.charts_config_path() == tmp_path / 'rev80' / 'charts.yaml'


def test_no_dearpygui_import():
    from pathlib import Path
    lines = Path(charts.__file__).read_text().splitlines()
    imports = [ln for ln in lines if ln.lstrip().startswith(('import ', 'from '))]
    assert not any('dearpygui' in ln for ln in imports)


# --- Settings before the Charts tab ------------------------------------------

def test_legacy_settings_add_an_envelope_chart_and_spectrum_averaging():
    base = charts.default_layout([0, 1], lambda ch: ('in/s', '0-P'))
    cs = charts.legacy_layout(base, envelope_enabled=True, envelope_unit='g',
                              averaging_enabled=True, n_averages=6)
    assert [c.chart_type for c in cs.charts] == ['waveform', 'spectrum', 'envelope']
    env = cs.charts[2]
    assert (env.channels, env.unit, env.amplitude_mode) == ((0, 1), 'g', '0-P')
    assert env.chart_id not in {'c1', 'c2'}
    sp = cs.charts[1]
    assert (sp.averaging, sp.n_averages) == (True, 6)


def test_legacy_settings_off_change_nothing():
    """No trend is added: the default layout is a waveform and a spectrum."""
    base = charts.default_layout([0], lambda ch: ('in/s', '0-P'))
    assert charts.legacy_layout(base, envelope_enabled=False, envelope_unit='g',
                                averaging_enabled=False, n_averages=8) == base


def test_collector_layout_is_the_default_until_one_is_set():
    import rev80 as vc
    cfg = vc.AcquisitionSettings()
    cfg.enabled_channels = [0, 2]
    cfg.channel_roles = {2: 'tachometer'}
    dc = vc.DataCollector(config=cfg)
    assert dc.chart_set is None
    default = dc.chart_layout()
    assert [c.channels for c in default.charts] == [(0,), (0,)]
    assert [c.chart_type for c in default.charts] == ['waveform', 'spectrum']
    own = ChartSet((_spec(channels=(0,)),))
    dc.chart_set = own
    assert dc.chart_layout() is own
