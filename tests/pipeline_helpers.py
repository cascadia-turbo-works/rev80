"""One render tick, as the GUI runs it, for tests.

`tick(dc)`: one snapshot, `advance_frame()`, then the display results
(the averaging of the first spectrum chart). `view_of(dc, ch, sample)`: the
record view of one sample that is not in the cache.
`set_spectrum_averaging(dc, n)`: the spectrum charts of the layout in
effect average `n` frames.
"""


def tick(dc, unit=None, amplitude_mode=None):
    """Advance the displayed frame and return its display results."""
    snap = dc.snapshot()
    dc.advance_frame(snap)
    return dc.results_for(snap, unit, amplitude_mode,
                          n_averages=display_n_averages(dc))


def display_n_averages(dc):
    """Frames that the first spectrum chart averages, as the GUI uses it."""
    spec = next((c for c in dc.chart_layout().charts if c.chart_type == 'spectrum'), None)
    return dc.n_averages_for(spec) if spec is not None else 1


def set_spectrum_averaging(dc, n, enabled=True):
    """Set the averaging of every spectrum chart of the layout in effect."""
    from rev80.charts import ChartSet
    dc.chart_set = ChartSet(tuple(
        c.evolve(averaging=enabled, n_averages=n) if c.chart_type == 'spectrum' else c
        for c in dc.chart_layout().charts))


def view_of(dc, ch, sample, unit=None, amplitude_mode=None):
    """The view of one sample in the channel's record unit and mode (or the given ones)."""
    rec_unit, rec_mode = dc.default_view_of(ch)
    unit = unit or rec_unit
    if not dc._reachable(ch, unit):
        return None
    return dc._view_of_sample(ch, sample, unit, amplitude_mode or rec_mode)
