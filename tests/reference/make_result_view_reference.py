"""Write result_view_reference.npz: ChannelResults of the pre-refactor path.

Run once, from the repository root, at the commit before the measurement-
path refactor (part B of the plot-setup plan, 1417ccb):

    python tests/reference/make_result_view_reference.py

It drives the old `DataCollector.process_samples()` with off-bin tones plus
noise, for every unit and amplitude mode, with and without averaging.
`tests/test_result_view_equality.py` builds the same frames and requires
`result_view()` to give the same arrays. Do not run it again after the
refactor: the reference must come from the old code.
"""

from datetime import datetime
from pathlib import Path

import numpy as np

import rev80 as vc
from rev80.scope_sensor import ScopeSensor

OUT = Path(__file__).with_name('result_view_reference.npz')

#: (target unit, amplitude mode, averaging N or 0, sensor or None)
CASES = (
    [(u, '0-P', 0, 'g') for u in ('g', 'mm/s2', 'in/s2', 'mm/s', 'in/s', 'mil/s',
                                   'mm', 'in', 'mil')]
    + [('in/s', 'RMS', 0, 'g'), ('in/s', 'P-P', 0, 'g'), ('g', 'RMS', 0, 'g'),
       ('mV', '0-P', 0, None), ('g', 'RMS', 4, 'g'), ('in/s', '0-P', 4, 'g'),
       ('mm', 'P-P', 4, 'g')]
)
N_FRAMES = 6
FIELDS = ('time_data', 'time_vec', 'freq', 'spectrum', 'peaks')
SCALARS = ('overall', 'crest_factor', 'kurtosis', 'n_averages', 'samplerate')


def make_collector(unit, mode, n_avg, sensor):
    cfg = vc.AcquisitionSettings()
    cfg.maxfreq = 1000.0
    cfg.binsize = 2.0
    cfg.enabled_channels = [0]
    cfg.channel_target_units = {0: unit} if sensor else {}
    cfg.channel_amplitude_modes = {0: mode}
    cfg.averaging_enabled = n_avg > 0
    cfg.n_averages = max(1, n_avg)
    dc = vc.DataCollector(config=cfg)
    if sensor:
        dc.set_scope_sensor(0, ScopeSensor(name='acc', engineering_units=sensor,
                                           sensitivity=100.0, id='acc'))
    dc.init_trend_channels()
    return dc


def frame_block(dc, i):
    """Off-bin tones with non-zero phase, plus noise, at the raw rate, in mV."""
    fs = dc.config.raw_samplerate
    n = dc.config.raw_blocksize
    t = np.arange(n) / fs + i * n / fs
    rng = np.random.default_rng(100 + i)
    return (80.0 * np.sin(2 * np.pi * 61.3 * t + 0.7)
            + 25.0 * np.sin(2 * np.pi * 437.9 * t + 1.9)
            + 3.0 * rng.standard_normal(n))


def feed(dc, i):
    dc.receive_data({
        'data': frame_block(dc, i)[:, None], 'channels': [0], 'status': 'OKAY',
        'timestamp': datetime(2026, 10, 19), 'rel_time': i * dc.config.acquisition_period,
        'samplerate': dc.config.raw_samplerate, 'overflow_mask': 0, 'degraded': False,
    })


def main():
    out = {}
    for k, (unit, mode, n_avg, sensor) in enumerate(CASES):
        dc = make_collector(unit, mode, n_avg, sensor)
        for i in range(N_FRAMES):
            feed(dc, i)
        (r,) = dc.process_samples()        # browse mode: the newest frame
        for f in FIELDS:
            out[f'{k}_{f}'] = np.asarray(getattr(r, f))
        for f in SCALARS:
            out[f'{k}_{f}'] = np.asarray(float(getattr(r, f)))
        out[f'{k}_unit'] = np.asarray(r.unit)
    np.savez_compressed(OUT, **out)
    print(f'wrote {OUT} ({OUT.stat().st_size} bytes, {len(CASES)} cases)')


if __name__ == '__main__':
    main()
