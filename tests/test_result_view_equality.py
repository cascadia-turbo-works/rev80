"""result_view() gives the arrays of the pre-refactor path.

The reference `tests/reference/result_view_reference.npz` was written by
`tests/reference/make_result_view_reference.py` with the old
`DataCollector.process_samples()`, before part B of the plot-setup work.
The same frames go through the snapshot and `result_view()` here.

Axes, peak indices and counts must be identical. Float values must agree
to `FLOAT_TOL` of the array's full scale, not bit for bit: the stored
reference is one machine's FFT and BLAS rounding. The old code on another
machine differs from it by up to 1.1e-10 of full scale (spectrum; CI and a
Linux container, numpy 2.5.4, scipy 1.18.1). A change to the algorithm
moves values by orders of magnitude more than `FLOAT_TOL`.
"""

import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).with_name('reference')))
import make_result_view_reference as ref  # noqa: E402

DATA = np.load(Path(__file__).with_name('reference') / 'result_view_reference.npz')

#: Fields with no floating-point arithmetic that depends on the platform.
EXACT = ('time_vec', 'freq', 'peaks', 'n_averages', 'samplerate')
#: Largest difference allowed, as a fraction of the reference full scale.
#: About 9x the largest difference measured across platforms (1.1e-10).
FLOAT_TOL = 1e-9


def _check(k, f, actual, desired):
    actual = np.atleast_1d(np.asarray(actual))
    desired = np.atleast_1d(desired)
    msg = f'case {k} {ref.CASES[k]} {f}'
    if f in EXACT:
        np.testing.assert_array_equal(actual, desired, err_msg=msg)
        return
    assert actual.shape == desired.shape, msg
    scale = float(np.max(np.abs(desired))) if desired.size else 0.0
    np.testing.assert_allclose(actual, desired, rtol=0.0,
                               atol=FLOAT_TOL * (scale or 1.0), err_msg=msg)


@pytest.mark.parametrize('k', range(len(ref.CASES)))
def test_result_view_equals_the_old_path(k):
    unit, mode, n_avg, sensor = ref.CASES[k]
    dc = ref.make_collector(unit, mode, n_avg, sensor)
    for i in range(ref.N_FRAMES):
        ref.feed(dc, i)
    snap = dc.snapshot()                    # browse mode: the newest frame
    r = dc.result_view(snap, 0, n_averages=dc.display_n_averages())
    assert r.unit == str(DATA[f'{k}_unit'])
    for f in ref.FIELDS + ref.SCALARS:
        _check(k, f, getattr(r, f), DATA[f'{k}_{f}'])
