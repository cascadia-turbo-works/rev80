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

