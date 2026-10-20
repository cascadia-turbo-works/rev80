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
    """`base` with the settings that came before the Charts tab.

    "Envelope analysis" on adds an envelope chart with the channels of the
    first spectrum, in `envelope_unit` (the sensor EU) 0-P. "Average
    spectrum" on sets the averaging of every spectrum chart to `n_averages`.
    """
    cs = base
    if averaging_enabled:
        cs = ChartSet(tuple(c.evolve(averaging=True, n_averages=n_averages)
                            if c.chart_type == 'spectrum' else c for c in cs.charts))
    if envelope_enabled and not any(c.chart_type == 'envelope' for c in cs.charts):
        spectrum = next((c for c in cs.charts if c.chart_type == 'spectrum'), None)
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


# ---------------------------------------------------------------------------
# Charts-tab edits (pure; the widgets are in gui_charts_tab.py)
# ---------------------------------------------------------------------------

def unit_label(unit: str, mode: str) -> str:
    """The text of a unit combo item: 'in/s RMS', or 'g' for a chart with no mode."""
    return f'{unit} {mode}' if mode else unit


def parse_unit_label(label: str) -> tuple[str, str]:
    """(unit, mode) of a `unit_label()` text."""
    unit, _, mode = label.partition(' ')
    return unit, mode


def vibration_channels_of(roles: Mapping[int, str]) -> list[int]:
    """The present channels that can be a series, in channel order."""
    return sorted(ch for ch, role in roles.items() if role != 'tachometer')


def unit_choices(spec: ChartSpec, roles: Mapping[int, str],
                 sensor_eus: Mapping[int, str | None]) -> list[str]:
    """The unit combo items of `spec`.

    The units that every checked, present channel can show; with none
    checked, those of every present vibration channel. The current unit
    and mode stay in the list, so the combo never changes them by itself.
    """
    checked = [ch for ch in spec.channels if ch in roles and roles[ch] != 'tachometer']
    eus = [sensor_eus.get(ch) for ch in (checked or vibration_channels_of(roles))]
    if not eus:
        units = list(UNITS)
    else:
        units = [u for u in UNITS
                 if all(unit_reachable(eu, u, spec.chart_type) for eu in eus)]
    items = [unit_label(u, m) for u in units for m in modes_for(spec.chart_type)]
    current = unit_label(spec.unit, spec.amplitude_mode)
    if current not in items:
        items.insert(0, current)
    return items


def with_channel(spec: ChartSpec, ch: int, on: bool) -> ChartSpec:
    """`spec` with `ch` checked or not. Checked channels stay in channel order."""
    channels = set(spec.channels)
    if on:
        channels.add(ch)
    else:
        channels.discard(ch)
    return spec.evolve(channels=tuple(sorted(channels)))


def with_xy(spec: ChartSpec, axis: int, ch: int) -> ChartSpec:
    """An XY chart with channel `ch` on axis 0 (X) or 1 (Y).

    An empty slot takes `ch` too, so the channel stays on its axis; the
    chart then says that XY needs two different channels.
    """
    pair = list(spec.channels[:2]) + [None] * (2 - len(spec.channels[:2]))
    pair[axis] = ch
    return spec.evolve(channels=tuple(ch if c is None else c for c in pair))


def swapped_xy(spec: ChartSpec) -> ChartSpec:
    return spec.evolve(channels=tuple(reversed(spec.channels[:2])))


def _free_name(chart_set: ChartSet, base: str) -> str:
    names = {c.name for c in chart_set.charts}
    if base not in names:
        return base
    n = 2
    while f'{base} {n}' in names:
        n += 1
    return f'{base} {n}'


def new_chart(chart_set: ChartSet, chart_type: str, roles: Mapping[int, str],
              sensor_eus: Mapping[int, str | None],
              record_unit_of: Callable[[int], tuple[str, str]]) -> ChartSpec:
    """A new chart of `chart_type` for the present channels, ready to edit.

    Unit and mode: the record unit of the first vibration channel; for an
    envelope chart, its sensor EU, 0-P. Channels: every vibration channel
    that can show that unit; for XY, the first two. A trend gets the shaft
    speed of the first tachometer channel, if there is one.
    """
    if chart_type not in CHART_TYPES:
        raise ValueError(f'unknown chart type {chart_type!r}')
    vib = vibration_channels_of(roles)
    if chart_type == 'envelope':
        eu = sensor_eus.get(vib[0]) if vib else None
        unit, mode = (eu or 'mV'), '0-P'
    else:
        unit, mode = record_unit_of(vib[0]) if vib else ('mV', '0-P')
        mode = (mode or '0-P') if chart_type in MODE_CHART_TYPES else ''
    channels = tuple(ch for ch in vib
                     if unit_reachable(sensor_eus.get(ch), unit, chart_type))
    if chart_type == 'xy':
        channels = channels[:2]
    tachs = sorted(ch for ch, role in roles.items() if role == 'tachometer')
    is_trend = chart_type == 'trend'
    return ChartSpec(
        chart_id=chart_set.new_chart_id(), chart_type=chart_type,
        name=_free_name(chart_set, CHART_TYPE_LABELS[chart_type]),
        channels=channels, unit=unit, amplitude_mode=mode,
        show_rpm=is_trend and bool(tachs),
        tach_channel=tachs[0] if is_trend and tachs else None)
