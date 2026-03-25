import pytest
import vibechecker as vc


def test_default_instance():
    config = vc.AcquisitionSettings()
    assert isinstance(config, vc.AcquisitionSettings)
    assert config.enabled_channels == [0]
    assert config.coupling == 'AC'
    assert config.voltage_range_for(0) == 10


def test_maxfreq_drives_samplerate():
    config = vc.AcquisitionSettings()
    config.maxfreq = 1000
    assert config.samplerate >= 2000


def test_binsize_drives_blocksize():
    config = vc.AcquisitionSettings()
    config.binsize = 1.0
    # blocksize must be large enough to achieve the requested bin size
    assert config.samplerate / config.blocksize <= 1.0


@pytest.mark.parametrize('df', [1.0, 5.0, 20.0])
def test_ensure_binsize_satisfies_constraint(df):
    config = vc.AcquisitionSettings()
    config.ensure_binsize(df)
    assert config.binsize <= df
    assert config.samplerate / config.blocksize <= df


def test_copy_preserves_blocksize_and_samplerate():
    original = vc.AcquisitionSettings()
    original.blocksize = 512
    original.samplerate = 8000
    copy = vc.AcquisitionSettings.copy(original)
    assert copy.blocksize == 512
    assert copy.samplerate == 8000


def test_instances_have_independent_enabled_channels():
    a = vc.AcquisitionSettings()
    b = vc.AcquisitionSettings()
    a.enabled_channels.append(1)
    assert b.enabled_channels == [0]


def test_voltage_range_for_per_channel():
    config = vc.AcquisitionSettings()
    config.channel_voltage_ranges = {0: 5, 1: 8}
    assert config.voltage_range_for(0) == 5
    assert config.voltage_range_for(1) == 8
    assert config.voltage_range_for(3) == 10   # unknown → default
