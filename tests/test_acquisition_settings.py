import pytest

import rev80
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


def test_samplerate_is_exactly_2p56x_maxfreq():
    """The display rate is exactly 2.56 x F_max at every preset (no rounding)."""
    config = AcquisitionSettings()
    for fm in rev80.MAXFREQ_PRESETS:
        config.maxfreq = fm
        assert config.samplerate == int(round(2.56 * fm)), (
            f'F_max={fm}: samplerate {config.samplerate} != 2.56 x {fm}'
        )


def test_display_rate_never_exceeds_acquisition_rate():
    """At every preset, the display rate is not more than the raw rate.

    decimate_to_rate does not upsample, so a display rate above the raw rate
    would be stated but never produced. The maxfreq setter clamps to this.
    """
    config = AcquisitionSettings()
    for fm in rev80.MAXFREQ_PRESETS:
        config.maxfreq = fm
        assert config.maxfreq == fm, (
            f'F_max={fm} was clamped to {config.maxfreq} -- RAW_SAMPLERATE_HZ '
            f'({config.raw_samplerate}) cannot back the preset grid'
        )
        assert config.samplerate <= config.raw_samplerate, (
            f'F_max={fm}: display rate {config.samplerate} exceeds acquisition '
            f'rate {config.raw_samplerate}'
        )


def test_decimation_ratio_is_an_exact_integer_at_every_preset():
    """At the nominal raw rate, raw/display is an integer at every preset.

    This keeps the polyphase resampler short. It is why RAW_SAMPLERATE_HZ is
    2.56 x the top F_max preset.
    """
    config = AcquisitionSettings()
    for fm in rev80.MAXFREQ_PRESETS:
        config.maxfreq = fm
        ratio = config.raw_samplerate / config.samplerate
        assert ratio == int(ratio), (
            f'F_max={fm}: raw/display = {ratio}, not an integer'
        )


def test_blocksize_delivers_the_requested_binsize():
    """The delivered bin is never coarser than requested, and a frame is 1/binsize s.

    blocksize need not be a power of two (CONTRIBUTING.md, "E11").
    """
    config = AcquisitionSettings()
    for fm in rev80.MAXFREQ_PRESETS:
        for df in rev80.BINSIZE_PRESETS:
            config.maxfreq = fm
            config.binsize = df
            assert config.binsize_actual <= df + 1e-9, (
                f'F_max={fm} df={df}: delivered bin {config.binsize_actual} '
                f'is coarser than requested'
            )
            # A frame is 1/binsize seconds, rounded up to a whole sample:
            # never shorter, and not more than one sample longer.
            ideal = 1.0 / df
            assert config.acquisition_period >= ideal - 1e-12, (
                f'F_max={fm} df={df}: frame {config.acquisition_period} s is '
                f'shorter than the {ideal} s the requested bin needs'
            )
            assert config.acquisition_period < ideal + 1.0 / config.samplerate, (
                f'F_max={fm} df={df}: frame {config.acquisition_period} s '
                f'overshoots {ideal} s by more than one sample'
            )


def test_n_fft_bins():
    """n_fft_bins and binsize_actual agree with the spectrum that Welch computes.

    The test runs Welch at all preset combinations; it does not restate the
    formula for n_fft_bins.
    """
    import numpy as np
    import scipy.signal

    from rev80.util import MAXFREQ_PRESETS, BINSIZE_PRESETS

    for maxfreq in MAXFREQ_PRESETS:
        for binsize in BINSIZE_PRESETS:
            config = AcquisitionSettings()
            config.maxfreq = maxfreq
            config.binsize = binsize

            freq, _ = scipy.signal.welch(
                np.zeros(config.blocksize), fs=float(config.samplerate),
                window=config.fft_window, nperseg=config.nperseg,
                noverlap=int(config.nperseg * config.welch_overlap),
                nfft=config.nperseg, scaling='spectrum',
            )
            # Only the band up to maxfreq is displayed; process_sample removes
            # the guard band between maxfreq and fs/2.
            displayed = int((freq <= config.maxfreq).sum())
            assert config.n_fft_bins == displayed, (
                f'F_max={maxfreq} df={binsize}: n_fft_bins states '
                f'{config.n_fft_bins}, displayed spectrum has {displayed} lines'
            )
            # Stated bin width must be the one actually delivered, and must
            # never be coarser than the user's request.
            assert config.binsize_actual == pytest.approx(freq[1] - freq[0])
            assert config.binsize_actual <= binsize * 1.0001


def test_memory_bytes():
    """memory_bytes uses raw_blocksize: frame_cache and HDF5 hold raw-rate data."""
    config = AcquisitionSettings()
    assert config.memory_bytes == config.raw_blocksize * 8


def test_filter_defaults():
    """Filter fields have valid types and sane ranges regardless of the default values."""
    config = AcquisitionSettings()
    assert isinstance(config.highpass_enabled, bool)
    assert config.highpass_fc > 0


def test_welch_overlap_default():
    config = AcquisitionSettings()
    assert 0.0 <= config.welch_overlap <= 0.95


# ---------------------------------------------------------------------------
# Channel roles (vibration or tachometer)
# ---------------------------------------------------------------------------

def test_channels_are_vibration_by_default():
    """A channel with no role set is a vibration channel."""
    config = AcquisitionSettings()
    assert config.role_for(0) == 'vibration'
    assert config.role_for(7) == 'vibration'
    assert config.channel_roles == {}


def test_role_partitions_enabled_channels():
    config = AcquisitionSettings()
    config.enabled_channels = [0, 1, 3]
    config.channel_roles = {3: 'tachometer'}
    assert config.vibration_channels == [0, 1]
    assert config.tach_channels == [3]


def test_role_partition_ignores_disabled_channels():
    """A tachometer role on a disabled channel does not make a tachometer channel."""
    config = AcquisitionSettings()
    config.enabled_channels = [0]
    config.channel_roles = {3: 'tachometer'}
    assert config.tach_channels == []
    assert config.vibration_channels == [0]


def test_unknown_role_string_falls_back_to_vibration():
    """A hand-edited YAML must not be able to invent a third channel kind."""
    config = AcquisitionSettings()
    config.channel_roles = {0: 'keyphasor'}
    assert config.role_for(0) == 'vibration'


def test_copy_carries_channel_roles():
    """AcquisitionSettings.copy() carries channel_roles.

    The per-channel dicts are outside the to_dict/from_dict round trip, so
    copy() lists them by name. A dict not in that list is lost on copy.
    """
    config = AcquisitionSettings()
    config.enabled_channels = [0, 1]
    config.channel_roles = {1: 'tachometer'}
    dup = AcquisitionSettings.copy(config)
    assert dup.channel_roles == {1: 'tachometer'}
    assert dup.tach_channels == [1]


def test_copy_deep_copies_channel_roles():
    config = AcquisitionSettings()
    config.channel_roles = {1: 'tachometer'}
    dup = AcquisitionSettings.copy(config)
    dup.channel_roles[2] = 'tachometer'
    assert 2 not in config.channel_roles, 'copy must not alias the original dict'


# ---------------------------------------------------------------------------
# Speed gate
# ---------------------------------------------------------------------------

def test_speed_gate_defaults_to_off():
    """The speed gate is off by default: with no tachometer, it would reject every frame."""
    config = AcquisitionSettings()
    assert config.speed_gate_enabled is False
    assert config.speed_gate_rpm is None
    assert config.speed_gate_tolerance_pct == 3.0


def test_speed_gate_round_trips_through_dict():
    """The speed gate settings round-trip through to_dict/from_dict."""
    config = AcquisitionSettings()
    config.speed_gate_enabled = True
    config.speed_gate_rpm = 1780.0
    config.speed_gate_tolerance_pct = 1.5
    restored = AcquisitionSettings.from_dict(config.to_dict())
    assert restored.speed_gate_enabled is True
    assert restored.speed_gate_rpm == 1780.0
    assert restored.speed_gate_tolerance_pct == 1.5


def test_speed_gate_rpm_none_survives_the_round_trip():
    """speed_gate_rpm None round-trips as None (take the first valid frame's speed)."""
    config = AcquisitionSettings()
    config.speed_gate_rpm = None
    assert AcquisitionSettings.from_dict(config.to_dict()).speed_gate_rpm is None


def test_speed_gate_survives_copy():
    config = AcquisitionSettings()
    config.speed_gate_enabled = True
    config.speed_gate_rpm = 3550.0
    dup = AcquisitionSettings.copy(config)
    assert dup.speed_gate_enabled is True
    assert dup.speed_gate_rpm == 3550.0
