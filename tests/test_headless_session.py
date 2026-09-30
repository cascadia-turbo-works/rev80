"""The session that rev80-headless builds from its arguments and config."""

from types import SimpleNamespace

import rev80 as vc
from rev80 import headless


def _args(tmp_path):
    return SimpleNamespace(interval=60.0, pre_buffer=5.0, burst_duration=10.0,
                           output=str(tmp_path), no_compress=False)


def _dc():
    cfg = vc.AcquisitionSettings()
    cfg.enabled_channels = [0]
    return vc.DataCollector(config=cfg)


def test_headless_reads_compression_level_from_config(tmp_path):
    """monitor.compression_level in acquisition.yaml reaches the session."""
    dc, args = _dc(), _args(tmp_path)
    session = headless._build_session(
        dc, args, 'lvl', mon_cfg={'compression_level': 9})
    assert session.compression == 'gzip'
    assert session.compression_level == 9

    default = headless._build_session(dc, args, 'lvl2', mon_cfg={})
    assert default.compression_level == 4


def test_session_id_is_local_time_like_start_time(tmp_path, monkeypatch):
    """The session id and start_time use the same local clock as the GUI."""
    import time
    from datetime import datetime

    monkeypatch.setenv('TZ', 'Pacific/Kiritimati')     # UTC+14: never UTC
    time.tzset()
    try:
        session_id, start_time = headless._new_session_id()
        assert start_time.tzinfo is None
        assert session_id == start_time.strftime('%Y-%m-%d-%H%M%S')
        assert abs((datetime.now() - start_time).total_seconds()) < 5

        session = headless._build_session(
            _dc(), _args(tmp_path), session_id, start_time=start_time)
        assert session.session_id == session_id
        assert session.start_time == start_time
    finally:
        monkeypatch.delenv('TZ')
        time.tzset()


def test_full_accuracy_ceiling_uses_the_achieved_rate():
    from rev80 import tach
    from rev80.tach import TachSettings

    cfg = vc.AcquisitionSettings()
    cfg.enabled_channels = [3]
    cfg.channel_roles = {3: 'tachometer'}
    settings = {3: TachSettings(pulses_per_rev=6)}
    achieved = 25591.8

    text = "\n".join(headless._tach_summary_lines(cfg, settings, samplerate=achieved))
    expected = achieved * 60.0 / (tach.MIN_SAMPLES_PER_PULSE * 6)
    assert f'{expected:,.0f}' in text
    assert 'nominal' not in text

    text = "\n".join(headless._tach_summary_lines(cfg, settings))
    nominal = cfg.raw_samplerate * 60.0 / (tach.MIN_SAMPLES_PER_PULSE * 6)
    assert f'{nominal:,.0f}' in text
    assert 'nominal' in text


def test_achieved_raw_rate_comes_from_the_latest_frame():
    from collections import deque
    from datetime import datetime, timezone

    import numpy as np

    from rev80.sample import VibeSample

    dc = _dc()
    assert headless._achieved_raw_rate(dc) is None
    dc.data['frame_cache'] = deque([{0: VibeSample(
        status='OKAY', _timestamp=datetime.now(timezone.utc),
        samplerate=25591.8, unit='mV', overflow=False, data=np.zeros(8))}])
    assert headless._achieved_raw_rate(dc) == 25591.8
