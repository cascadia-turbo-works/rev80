"""result_view() gives the arrays of the pre-refactor path, bit for bit.

The reference `tests/reference/result_view_reference.npz` was written by
`tests/reference/make_result_view_reference.py` with the old
`DataCollector.process_samples()`, before part B of the plot-setup work.
The same frames go through the snapshot and `result_view()` here.
"""

import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).with_name('reference')))
import make_result_view_reference as ref  # noqa: E402

DATA = np.load(Path(__file__).with_name('reference') / 'result_view_reference.npz')


@pytest.mark.parametrize('k', range(len(ref.CASES)))
def test_result_view_equals_the_old_path(k):
    unit, mode, n_avg, sensor = ref.CASES[k]
    dc = ref.make_collector(unit, mode, n_avg, sensor)
    for i in range(ref.N_FRAMES):
        ref.feed(dc, i)
    snap = dc.snapshot()                    # browse mode: the newest frame
    # The old path averaged min(N, cache_frames) frames when averaging was on.
    n = min(n_avg, dc.config.cache_frames) if n_avg > 0 else 1
    r = dc.result_view(snap, 0, n_averages=n)
    assert r.unit == str(DATA[f'{k}_unit'])
    for f in ref.FIELDS:
        np.testing.assert_array_equal(np.asarray(getattr(r, f)), DATA[f'{k}_{f}'],
                                      err_msg=f'case {k} {ref.CASES[k]} {f}')
    for f in ref.SCALARS:
        assert float(getattr(r, f)) == float(DATA[f'{k}_{f}']), (k, f)
