import pytest
from rev80 import AcquisitionSettings


def test_default_instance():
    config = AcquisitionSettings()
    assert isinstance(config, AcquisitionSettings)
    assert config.enabled_channels == [0]
    assert config.coupling == 'AC'
    assert isinstance(config.voltage_range_for(0), int)
    assert 0 <= config.voltage_range_for(0) <= 13   # valid PS4000A range index


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
def test_binsize_satisfies_constraint(df):
    config = AcquisitionSettings()
    config.binsize = df
    assert config.samplerate / config.blocksize <= df


def test_copy_preserves_maxfreq_and_binsize():
    original = AcquisitionSettings()
    original.maxfreq = 5000
    original.binsize = 2.0
    copy = AcquisitionSettings.copy(original)
    assert copy.maxfreq == 5000
    assert copy.binsize == 2.0
    assert copy.samplerate == original.samplerate
    assert copy.blocksize == original.blocksize


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
    assert 0 <= config.voltage_range_for(3) <= 13   # unknown ch → valid default index


def test_trend_max_points_is_positive_int():
    config = AcquisitionSettings()
    assert isinstance(config.trend_max_points, int)
    assert config.trend_max_points > 0


def test_samplerate_is_power_of_two():
    config = AcquisitionSettings()
    for fm in [200, 500, 1000, 5000, 10000, 50000]:
        config.maxfreq = fm
        sr = config.samplerate
        assert sr & (sr - 1) == 0, f'samplerate {sr} is not a power of 2'


def test_blocksize_is_power_of_two():
    config = AcquisitionSettings()
    for df in [0.25, 0.5, 1.0, 2.0, 5.0, 10.0]:
        config.binsize = df
        bs = config.blocksize
        assert bs & (bs - 1) == 0, f'blocksize {bs} is not a power of 2'


def test_n_fft_bins():
    config = AcquisitionSettings()
    assert config.n_fft_bins == config.blocksize // 2 + 1


def test_memory_bytes():
    config = AcquisitionSettings()
    assert config.memory_bytes == config.blocksize * 8


def test_filter_defaults():
    """Filter fields have valid types and sane ranges regardless of the default values."""
    config = AcquisitionSettings()
    assert isinstance(config.highpass_enabled, bool)
    assert config.highpass_fc > 0


def test_welch_overlap_default():
    config = AcquisitionSettings()
    assert 0.0 <= config.welch_overlap <= 0.95
