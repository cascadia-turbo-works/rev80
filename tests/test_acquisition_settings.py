import pytest
from vibechecker import AcquisitionSettings


def test_default_instance():
    config = AcquisitionSettings()
    assert isinstance(config, AcquisitionSettings)
    assert config.enabled_channels == [0]
    assert config.coupling == 'AC'
    assert config.voltage_range_for(0) == 10


def test_maxfreq_drives_samplerate():
    config = AcquisitionSettings()
    config.maxfreq = 1000
    assert config.samplerate >= 2000


def test_binsize_drives_blocksize():
    config = AcquisitionSettings()
    config.binsize = 1.0
    # blocksize must be large enough to achieve the requested bin size
    assert config.samplerate / config.blocksize <= 1.0


@pytest.mark.parametrize('df', [1.0, 5.0, 20.0])
def test_ensure_binsize_satisfies_constraint(df):
    config = AcquisitionSettings()
    config.ensure_binsize(df)
    assert config.binsize <= df
    assert config.samplerate / config.blocksize <= df


def test_copy_preserves_blocksize_and_samplerate():
    original = AcquisitionSettings()
    original.blocksize = 512
    original.samplerate = 8000
    copy = AcquisitionSettings.copy(original)
    assert copy.blocksize == 512
    assert copy.samplerate == 8000


def test_instances_have_independent_enabled_channels():
    cfg_a = AcquisitionSettings()
    cfg_b = AcquisitionSettings()
    cfg_a.enabled_channels.append(1)
    assert cfg_b.enabled_channels == [0]


def test_voltage_range_for_per_channel():
    config = AcquisitionSettings()
    config.channel_voltage_ranges = {0: 5, 1: 8}
    assert config.voltage_range_for(0) == 5
    assert config.voltage_range_for(1) == 8
    assert config.voltage_range_for(3) == 10   # unknown → default


def test_trend_max_points_is_positive_int():
    config = AcquisitionSettings()
    assert isinstance(config.trend_max_points, int)
    assert config.trend_max_points > 0


def test_trend_fmin_is_non_negative():
    config = AcquisitionSettings()
    assert config.trend_fmin >= 0.0


def test_trend_fmax_is_none_or_positive():
    """trend_fmax=None means 'clamp to maxfreq at compute time'."""
    config = AcquisitionSettings()
    assert config.trend_fmax is None or config.trend_fmax > 0
