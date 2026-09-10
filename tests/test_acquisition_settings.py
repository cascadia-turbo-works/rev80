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
    """The display rate is the ratio the dialog advertises, not a rounded-up one.

    Replaces test_samplerate_is_power_of_two. nextpow2(2.56 * maxfreq)
    overstated the rate by up to 2x; at the top preset that meant advertising
    32768 Hz against 25600 Hz of real data. A power-of-two *rate* buys nothing
    -- the FFT length is blocksize, tested separately.
    """
    config = AcquisitionSettings()
    for fm in rev80.MAXFREQ_PRESETS:
        config.maxfreq = fm
        assert config.samplerate == int(round(2.56 * fm)), (
            f'F_max={fm}: samplerate {config.samplerate} != 2.56 x {fm}'
        )


def test_display_rate_never_exceeds_acquisition_rate():
    """You cannot display a rate you did not acquire.

    The bug this pins: decimate_to_rate returns the block undecimated when
    target_rate >= raw_rate, so an overstated samplerate does not fail loudly
    -- the dialog simply advertises a rate the pipeline never produces, and
    n_fft_bins / binsize_actual are computed from it. Every preset must
    satisfy samplerate <= raw_samplerate, which is exactly the condition
    maxfreq's setter clamps to.
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
    """raw -> display decimation should be a clean integer factor.

    Not a correctness requirement on its own, but it is the property that
    makes the polyphase resampler cheap and exact, and it is what picks
    RAW_SAMPLERATE_HZ = 2.56 x the top preset over any nearby value.
    """
    config = AcquisitionSettings()
    for fm in rev80.MAXFREQ_PRESETS:
        config.maxfreq = fm
        ratio = config.raw_samplerate / config.samplerate
        assert ratio == int(ratio), (
            f'F_max={fm}: raw/display = {ratio}, not an integer'
        )


def test_blocksize_delivers_the_requested_binsize():
    """Replaces test_blocksize_is_power_of_two.

    blocksize is a Welch segment length, and pocketfft is efficient for any
    5-smooth length -- being a power of two was never the invariant that
    mattered. What matters is that the delivered bin is never coarser than
    the requested one, and that a frame really is 1/binsize seconds.
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
            # A frame is 1/binsize seconds, rounded up to a whole sample --
            # never shorter (you cannot resolve df from less data) and never
            # more than one sample longer. The dialog's "a frame is exactly
            # 1/binsize seconds" only ever held when samplerate/binsize landed
            # on a power of two; with nextpow2 the overshoot reached 56.2%
            # (F_max=200, df=50: 31.2 ms for a nominal 20 ms). This bounds it.
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
    """n_fft_bins must describe the spectrum that is actually computed.

    The old assertion (`n_fft_bins == blocksize // 2 + 1`) merely restated the
    implementation, so it stayed green while the Welch call produced a
    different number of lines at 40 of the 72 preset combinations (F-8).
    The real invariant is that the stated line count and the stated bin width
    agree with each other and with the block that is actually transformed.
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
            # Only the band up to maxfreq is displayed; the guard band between
            # maxfreq and fs/2 is discarded in process_sample (F-9).
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
    """Against raw_blocksize, not blocksize: frame_cache/HDF5 hold the raw
    (acquisition-rate) data, not the maxfreq-decimated display view."""
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
# Channel roles (R43 — tachometer support)
# ---------------------------------------------------------------------------

def test_channels_are_vibration_by_default():
    """Every existing config predates roles and must keep behaving as before."""
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
    """A tach configured on a channel that is switched off is not a tach
    channel this run -- otherwise the collector would look for a pulse train
    on an input nobody is sampling."""
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
    """AcquisitionSettings.copy() enumerates the per-channel dicts by name,
    because they live in the 'channels' config section and so are outside the
    to_dict/from_dict round trip. A sixth dict added without editing that tuple
    is audit H-08 again: the copy silently reverts every tachometer channel to
    vibration, and the pipeline then high-passes a pulse train and reports
    kurtosis ~16 on it.
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
# Speed gate (R43)
# ---------------------------------------------------------------------------

def test_speed_gate_defaults_to_off():
    """Off by default: with no tach fitted there is no reference to gate on,
    and a gate that fails closed would reject every frame."""
    config = AcquisitionSettings()
    assert config.speed_gate_enabled is False
    assert config.speed_gate_rpm is None
    assert config.speed_gate_tolerance_pct == 3.0


def test_speed_gate_round_trips_through_dict():
    """Scalars belong in to_dict/from_dict so a field added there is carried
    by copy() automatically."""
    config = AcquisitionSettings()
    config.speed_gate_enabled = True
    config.speed_gate_rpm = 1780.0
    config.speed_gate_tolerance_pct = 1.5
    restored = AcquisitionSettings.from_dict(config.to_dict())
    assert restored.speed_gate_enabled is True
    assert restored.speed_gate_rpm == 1780.0
    assert restored.speed_gate_tolerance_pct == 1.5


def test_speed_gate_rpm_none_survives_the_round_trip():
    """None means 'latch the reference from the first valid frame'. Writing a
    resolved value back would freeze one session's speed into the config --
    the same trap band_fmin/band_fmax already guard against."""
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
