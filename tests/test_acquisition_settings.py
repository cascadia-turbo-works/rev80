import pytest
import vibechecker as vc

def test_acq_default():
    config = vc.AcquisitionSettings()

    assert isinstance(config, vc.AcquisitionSettings)

@pytest.mark.parametrize('ns', vc.SAMPLERATES)
@pytest.mark.parametrize('fs', vc.BLOCKSIZES)
def test_acq_ensure(ns, fs):
    config = vc.AcquisitionSettings(ns,fs)

    for ns in vc.BINSIZES.__iter__():
        config.ensure_binsize(ns)
        assert config.binsize <= ns
        assert config.samplerate / config.blocksize <= ns

    # for fm in vc.MAXFREQS.__iter__():
    #     config.ensure_maxfreq(fm)
    #     assert config.maxfreq == fm
    #     assert config.samplerate / 2 >= fm


