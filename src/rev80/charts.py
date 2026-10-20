"""The chart layout: which channels show on which chart, in which unit.

The chart sets the unit and amplitude mode of every series on it. The
record unit of a channel (Channels tab) sets only what is stored. This
module holds plain data and pure checks: no dearpygui import, so the
converter for 0.x files and headless can use it.

The layout is stored in `charts.yaml` (live data) and in each data file
(`/metadata` attribute `chart_layout_json`). Both hold `ChartSet.to_dict()`.
"""

from __future__ import annotations

import dataclasses
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable, Mapping

import yaml

from rev80.util import AMPLITUDE_MODES, EU_OPTIONS, integration_steps

log = logging.getLogger(__name__)

CHART_TYPES = ('waveform', 'trend', 'spectrum', 'envelope', 'xy')
CHART_TYPE_LABELS = {
    'waveform': 'Time waveform',
    'trend':    'Trend',
    'spectrum': 'Spectrum',
    'envelope': 'Envelope',
    'xy':       'XY',
}
#: Chart types that have an amplitude mode. A waveform and an XY plot show
#: the signal itself.
MODE_CHART_TYPES = frozenset({'spectrum', 'trend', 'envelope'})
#: Every unit a chart can have, in the order of the unit combos.
UNITS = tuple(EU_OPTIONS)
#: The most integration or differentiation steps from the sensor EU.
MAX_INTEGRATION_STEPS = 2
LAYOUT_VERSION = 1
DEFAULT_N_AVERAGES = 8


@dataclass(frozen=True)
class ChartSpec:
    """One chart. `chart_id` is stable: widget tags come from it, never from the name."""
    chart_id: str
    chart_type: str
    name: str
    channels: tuple = ()          # display order; xy: (x, y)
    unit: str = 'mV'              # the unit of every series on the chart
    amplitude_mode: str = ''      # spectrum, trend, envelope; '' for waveform and xy
    show_rpm: bool = False        # trend: shaft speed on a second y axis
    tach_channel: int | None = None
    averaging: bool = False       # spectrum
    n_averages: int = DEFAULT_N_AVERAGES   # spectrum; clamped to the cache at use

    def __post_init__(self):
        object.__setattr__(self, 'channels', tuple(int(c) for c in self.channels))
        object.__setattr__(self, 'n_averages', max(1, int(self.n_averages)))

    def evolve(self, **changes) -> 'ChartSpec':
        """A copy with `changes`."""
        return dataclasses.replace(self, **changes)

    def to_dict(self) -> dict:
        d = dataclasses.asdict(self)
        d['channels'] = list(self.channels)
        return d

    @classmethod
    def from_dict(cls, d: Mapping) -> 'ChartSpec':
        """Raises ValueError or TypeError for an entry that is not a chart."""
        if not isinstance(d, Mapping):
            raise TypeError('not a mapping')
        chart_type = d.get('chart_type')
        if chart_type not in CHART_TYPES:
            raise ValueError(f'unknown chart type {chart_type!r}')
        chart_id = d.get('chart_id')
        if not isinstance(chart_id, str) or not chart_id:
            raise ValueError('no chart_id')
        channels = d.get('channels', [])
        if not isinstance(channels, (list, tuple)):
            raise TypeError('channels is not a list')
        tach = d.get('tach_channel')
        return cls(
            chart_id=chart_id,
            chart_type=chart_type,
            name=str(d.get('name') or CHART_TYPE_LABELS[chart_type]),
            channels=tuple(int(c) for c in channels),
            unit=str(d.get('unit') or 'mV'),
            amplitude_mode=str(d.get('amplitude_mode') or ''),
            show_rpm=bool(d.get('show_rpm', False)),
            tach_channel=None if tach is None else int(tach),
            averaging=bool(d.get('averaging', False)),
            n_averages=int(d.get('n_averages', DEFAULT_N_AVERAGES)),
        )


@dataclass(frozen=True)
class ChartSet:
    """The charts in tab order. Every edit returns a new set."""
    charts: tuple = ()

    def __post_init__(self):
        object.__setattr__(self, 'charts', tuple(self.charts))

    def chart(self, chart_id: str) -> ChartSpec | None:
        return next((c for c in self.charts if c.chart_id == chart_id), None)

    def new_chart_id(self) -> str:
        """An id that no chart in the set has, and higher than every 'c<n>' id."""
        used = [int(c.chart_id[1:]) for c in self.charts
                if c.chart_id[:1] == 'c' and c.chart_id[1:].isdigit()]
        n = max(used, default=0) + 1
        ids = {c.chart_id for c in self.charts}
        while f'c{n}' in ids:
            n += 1
        return f'c{n}'

    def with_chart(self, spec: ChartSpec) -> 'ChartSet':
        if self.chart(spec.chart_id) is not None:
            raise ValueError(f'chart id {spec.chart_id!r} is in use')
        return ChartSet(self.charts + (spec,))

    def replace_chart(self, spec: ChartSpec) -> 'ChartSet':
        return ChartSet(tuple(spec if c.chart_id == spec.chart_id else c
                              for c in self.charts))

    def without(self, chart_id: str) -> 'ChartSet':
        return ChartSet(tuple(c for c in self.charts if c.chart_id != chart_id))

    def to_dict(self) -> dict:
        return {'version': LAYOUT_VERSION, 'charts': [c.to_dict() for c in self.charts]}

    @classmethod
    def from_dict(cls, d) -> 'ChartSet':
        """The valid charts of `d`. A bad entry is skipped and logged."""
        entries = d.get('charts') if isinstance(d, Mapping) else None
        if not isinstance(entries, list):
            log.warning('Chart layout: no list of charts; the layout is empty')
            return cls(())
        charts: list[ChartSpec] = []
        ids: set[str] = set()
        for i, entry in enumerate(entries):
            try:
                spec = ChartSpec.from_dict(entry)
                if spec.chart_id in ids:
                    raise ValueError(f'chart id {spec.chart_id!r} is in use')
            except (TypeError, ValueError) as exc:
                log.warning('Chart layout: entry %d skipped: %s', i, exc)
                continue
            ids.add(spec.chart_id)
            charts.append(spec)
        return cls(tuple(charts))


# ---------------------------------------------------------------------------
# Units and channels
# ---------------------------------------------------------------------------

def unit_reachable(sensor_eu: str | None, unit: str, chart_type: str = 'spectrum') -> bool:
    """Can a channel with `sensor_eu` (None: no sensor) show `unit` on this chart type?

    No sensor: 'mV' only. With a sensor: the sensor EU itself (the Source EU
    combo offers 'mV'), or an engineering unit within two integration steps
    of it. An envelope chart allows the same quantity only (no integration).
    """
    if sensor_eu is None:
        return unit == 'mV'
    if unit == sensor_eu:
        return True
    if unit == 'mV' or sensor_eu == 'mV':
        return False
    try:
        steps = integration_steps(sensor_eu, unit)
    except ValueError:
        return False
    limit = 0 if chart_type == 'envelope' else MAX_INTEGRATION_STEPS
    return abs(steps) <= limit


def unreachable_reason(sensor_eu: str | None, unit: str, chart_type: str = 'spectrum') -> str:
    """Why `unit_reachable()` is False, for a legend or a tooltip."""
    if sensor_eu is None:
        return f'no sensor, cannot show {unit}'
    if unit == 'mV':
        return 'a sensor is assigned; mV is not an engineering unit'
    if chart_type == 'envelope':
        return f'an envelope chart shows the sensor quantity ({sensor_eu}), not {unit}'
    return f'more than two integration steps from {sensor_eu}'


def allowed_units(chart_type: str, sensor_eus: Iterable[str | None]) -> list[str]:
    """The units that every one of the checked channels can show, in combo order."""
    eus = list(sensor_eus)
    return [u for u in UNITS if all(unit_reachable(eu, u, chart_type) for eu in eus)]


def modes_for(chart_type: str) -> tuple:
    return tuple(AMPLITUDE_MODES) if chart_type in MODE_CHART_TYPES else ('',)


def channel_selectable(spec: ChartSpec, ch: int, roles: Mapping[int, str],
                       sensor_eus: Mapping[int, str | None]) -> tuple[bool, str]:
    """Can `ch` be checked on `spec`? (ok, reason)."""
    if roles.get(ch) == 'tachometer':
        return False, 'a tachometer channel; use it as the shaft speed of a trend'
    eu = sensor_eus.get(ch)
    if not unit_reachable(eu, spec.unit, spec.chart_type):
        return False, unreachable_reason(eu, spec.unit, spec.chart_type)
    return True, ''


def problems(spec: ChartSpec, roles: Mapping[int, str],
             sensor_eus: Mapping[int, str | None]) -> list[str]:
    """What the chart cannot show, one line each, for its tab. Empty when all is well.

    A channel that is absent now stays on the chart: the line says so.
    """
    out: list[str] = []
    if not spec.channels:
        return ['no channel selected']
    if spec.chart_type == 'xy' and (len(spec.channels) != 2
                                   or spec.channels[0] == spec.channels[1]):
        out.append('XY needs two different channels')
    for ch in dict.fromkeys(spec.channels):
        if ch not in roles:
            out.append(f'ch{ch}: not present')
            continue
        ok, why = channel_selectable(spec, ch, roles, sensor_eus)
        if not ok:
            out.append(f'ch{ch}: {why}')
    if spec.chart_type == 'trend' and spec.show_rpm and spec.tach_channel is not None:
        if roles.get(spec.tach_channel) != 'tachometer':
            out.append(f'ch{spec.tach_channel}: not a tachometer channel')
    return out


# ---------------------------------------------------------------------------
# Default layout and charts.yaml
# ---------------------------------------------------------------------------

def default_layout(vibration_channels: Iterable[int],
                   record_unit_of: Callable[[int], tuple[str, str]]) -> ChartSet:
    """One time waveform and one spectrum, with all vibration channels.

    Unit and mode: the record unit and mode of the first vibration channel
    (`record_unit_of(ch)` gives them); 'mV' with no channel.
    """
    channels = tuple(vibration_channels)
    unit, mode = record_unit_of(channels[0]) if channels else ('mV', '0-P')
    return ChartSet((
        ChartSpec('c1', 'waveform', CHART_TYPE_LABELS['waveform'], channels, unit, ''),
        ChartSpec('c2', 'spectrum', CHART_TYPE_LABELS['spectrum'], channels, unit,
                  mode or '0-P'),
    ))


def legacy_layout(base: ChartSet, *, envelope_enabled: bool, envelope_unit: str,
                  averaging_enabled: bool, n_averages: int) -> ChartSet:
    """`base` with the screen and the settings that came before the Charts tab.

    The 0.1.x window always had a Trend tab: a trend chart with the channels,
    unit and mode of the first spectrum is added if `base` has none.
    "Envelope analysis" on adds an envelope chart with the channels of the
    first spectrum, in `envelope_unit` (the sensor EU) 0-P. "Average
    spectrum" on sets the averaging of every spectrum chart to `n_averages`.
    """
    cs = base
    spectrum = next((c for c in cs.charts if c.chart_type == 'spectrum'), None)
    if spectrum is not None and not any(c.chart_type == 'trend' for c in cs.charts):
        cs = cs.with_chart(ChartSpec(cs.new_chart_id(), 'trend', CHART_TYPE_LABELS['trend'],
                                     spectrum.channels, spectrum.unit,
                                     spectrum.amplitude_mode))
    if averaging_enabled:
        cs = ChartSet(tuple(c.evolve(averaging=True, n_averages=n_averages)
                            if c.chart_type == 'spectrum' else c for c in cs.charts))
    if envelope_enabled and not any(c.chart_type == 'envelope' for c in cs.charts):
        channels = spectrum.channels if spectrum is not None else ()
        cs = cs.with_chart(ChartSpec(cs.new_chart_id(), 'envelope',
                                     CHART_TYPE_LABELS['envelope'], channels,
                                     envelope_unit, '0-P'))
    return cs


def load_chart_set(path: Path, default: Callable[[], ChartSet]) -> tuple[ChartSet, bool]:
    """The layout in `path`, and True; or `default()` and False.

    A missing, unreadable or invalid file, or one with no valid chart, gives
    the default. The file is never written here, so a bad file stays for the
    user to repair.
    """
    path = Path(path)
    if not path.exists():
        return default(), False
    try:
        with open(path) as f:
            data = yaml.safe_load(f)
    except (OSError, yaml.YAMLError, UnicodeDecodeError) as exc:
        log.warning('%s cannot be read (%s); the default chart layout is used, '
                    'and the file is not changed', path, exc)
        return default(), False
    cs = ChartSet.from_dict(data)
    if not cs.charts:
        log.warning('%s holds no valid chart; the default chart layout is used, '
                    'and the file is not changed', path)
        return default(), False
    return cs, True


def save_chart_set(path: Path, chart_set: ChartSet) -> None:
    """Write `chart_set` to `path` atomically."""
    from rev80.config import _atomic_yaml_write
    _atomic_yaml_write(Path(path), chart_set.to_dict())
