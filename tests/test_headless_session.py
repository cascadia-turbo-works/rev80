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

