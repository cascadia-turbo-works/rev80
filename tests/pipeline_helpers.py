"""One render tick, as the GUI runs it, for tests.

`tick(dc)`: one snapshot, `advance_frame()`, then the display results
(configured averaging). `view_of(dc, ch, sample)`: the record view of one
sample that is not in the cache.
"""


def tick(dc, unit=None, amplitude_mode=None):
    """Advance the displayed frame and return its display results."""
    snap = dc.snapshot()
    dc.advance_frame(snap)
    return dc.results_for(snap, unit, amplitude_mode,
                          n_averages=dc.display_n_averages())


def view_of(dc, ch, sample, unit=None, amplitude_mode=None):
    """The view of one sample in the channel's record unit and mode (or the given ones)."""
    rec_unit, rec_mode = dc.default_view_of(ch)
    unit = unit or rec_unit
    if not dc._reachable(ch, unit):
        return None
    return dc._view_of_sample(ch, sample, unit, amplitude_mode or rec_mode)
