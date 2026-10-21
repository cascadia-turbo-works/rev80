"""`rev80 convert-0x`: copy a Rev80 0.x data file into the format that Rev80 1.0 reads.

Rev80 1.0 reads measurement files of version 6 and monitor sessions of
version 7 only. This writes a converted COPY of a 0.x file and never
changes the source:

    measurement version 4 or 5  ->  <name>.v6.h5 beside it (or in --out)
    session version 6 (a session directory, or its session.h5)
                                ->  <directory>.v7/ beside it (or in --out)

The data does not change. The copy gets the new version number,
`rev80_version` = "convert-0x <version>", and `chart_layout_json` = the
default chart layout of `charts.default_layout()` with
`charts.record_view()`: the layout Rev80 1.0 gives a file with no stored
layout. A version-3 measurement file stores frames in the recorded unit,
not mV: save it again in Rev80 0.1.5 first.

Results go to the log (console and ~/Documents/Rev80/logs/), so a windowed
Windows install also records them.
"""

import argparse
import json
import shutil
from pathlib import Path

import h5py

import rev80
from rev80 import charts
from rev80.collector import _CONVERTIBLE_0X, DataCollector, _session_file_version

log = rev80.get_logger('convert_0x')

WRITER = f'convert-0x {rev80.__version__}'


class ConvertError(Exception):
    """A path that this script does not convert. The message says why."""


def _decode(x) -> str:
    return x.decode() if isinstance(x, bytes) else str(x)


def _frame_groups(f: h5py.File, kind: str):
    """Every frame group of the file: measurement frames, or session captures
    and burst frames."""
    if kind == 'measurement':
        yield from f.get('frames', {}).values()
        return
    yield from f.get('monitor', {}).values()
    for burst in f.get('burst', {}).values():
        if isinstance(burst, h5py.Group):
            yield from (g for k, g in burst.items() if k.isdigit())


def default_layout_for(f: h5py.File, kind: str) -> charts.ChartSet:
    """The Rev80 1.0 default layout for the channels and sensors of an open file.

    The vibration channels are the channels with data in the frames (as the
    loader takes them) that are not tachometer channels. Each record view
    follows `charts.record_view()`, with the sensor stored in the file.
    """
    meta = f['metadata']
    ch_meta = meta.get('channels', {})
    sensors = meta.get('scope_sensors', {})
    present: set[int] = set()
    for grp in _frame_groups(f, kind):
        present.update(int(k) for k in grp.keys() if k.isdigit())

    def role(ch: int) -> str:
        cg = ch_meta.get(str(ch))
        return _decode(cg.attrs.get('role', 'vibration')) if cg is not None else 'vibration'

    def view(ch: int) -> tuple[str, str]:
        cg = ch_meta.get(str(ch))
        if cg is None:
            return charts.record_view(None, '', '')
        sid = _decode(cg.attrs.get('scope_sensor_id', ''))
        eu = (_decode(sensors[sid].attrs.get('engineering_units', ''))
              if sid and sid in sensors else None)
        return charts.record_view(eu or None, _decode(cg.attrs.get('target_unit', '')),
                                  _decode(cg.attrs.get('amplitude_mode', '')))

    vibration = sorted(ch for ch in present if role(ch) != 'tachometer')
    return charts.default_layout(vibration, view)


def _kind_and_version(h5: Path) -> tuple[str, int]:
    with h5py.File(h5, 'r') as f:
        if 'metadata' not in f:
            raise ConvertError(f'{h5}: no /metadata group: not a Rev80 data file')
        kind = 'session' if 'monitor' in f else 'measurement'
        attrs = f['metadata'].attrs
        return kind, int(attrs.get('version', attrs.get('file_version', 3)))


def _plan(path: Path, out_dir: Path | None) -> tuple[str, int, Path, Path, Path]:
    """(kind, version, source to copy, destination, h5 file in the destination)."""
    if path.is_dir():
        h5 = path / 'session.h5'
        if not h5.is_file():
            raise ConvertError(f'{path}: a directory with no session.h5')
    elif path.is_file():
        h5 = path
    else:
        raise ConvertError(f'{path}: does not exist')
    kind, version = _kind_and_version(h5)
    current = DataCollector._FILE_VERSION if kind == 'measurement' else _session_file_version()
    if version == current:
        raise ConvertError(f'{h5}: already version {version}; Rev80 1.0 reads it')
    if version > current:
        raise ConvertError(f'{h5}: version {version} is newer than this Rev80 knows')
    if version not in _CONVERTIBLE_0X[kind]:
        hint = (' Open it in Rev80 0.1.5, save it again, then convert that copy.'
                if kind == 'measurement' else ' Open it with Rev80 0.1.5.')
        raise ConvertError(f'{h5}: {kind} version {version} is not converted.{hint}')
    if kind == 'measurement':
        dest = (out_dir or h5.parent) / f'{h5.stem}.v{current}.h5'
        return kind, version, h5, dest, dest
    session_dir = h5.parent
    dest = (out_dir or session_dir.parent) / f'{session_dir.name}.v{current}'
    return kind, version, session_dir, dest, dest / 'session.h5'


def convert(path: Path, out_dir: Path | None = None) -> Path:
    """Write the converted copy of `path`; return the destination. Raises ConvertError."""
    kind, _version, source, dest, dest_h5 = _plan(path, out_dir)
    if dest.exists():
        raise ConvertError(f'{dest}: exists; it is not overwritten')
    dest.parent.mkdir(parents=True, exist_ok=True)
    try:
        if source.is_dir():
            shutil.copytree(source, dest)
        else:
            shutil.copy2(source, dest)
        with h5py.File(dest_h5, 'a') as f:
            meta = f['metadata']
            if kind == 'measurement':
                meta.attrs['version'] = DataCollector._FILE_VERSION
            else:
                meta.attrs['file_version'] = _session_file_version()
            meta.attrs['rev80_version'] = WRITER
            meta.attrs['chart_layout_json'] = json.dumps(
                default_layout_for(f, kind).to_dict())
    except BaseException:
        # Never leave a half-written copy that Rev80 1.0 would read.
        if dest.is_dir():
            shutil.rmtree(dest, ignore_errors=True)
        else:
            dest.unlink(missing_ok=True)
        raise
    return dest


def build_option_parser() -> argparse.ArgumentParser:
    """The options of `rev80 convert-0x`, as a parent parser (no -h of its own)."""
    p = argparse.ArgumentParser(add_help=False)
    p.add_argument('paths', nargs='+', type=Path,
                   help='measurement .h5 files, session directories or session.h5 files')
    p.add_argument('--out', type=Path, default=None,
                   help='directory for the copies (default: beside each source)')
    return p


def run(args: argparse.Namespace) -> int:
    """Convert each path of `args`. Exit code 0 when all converted, else 1."""
    out_dir = args.out.expanduser() if args.out else None
    failed = 0
    for path in args.paths:
        try:
            dest = convert(path.expanduser(), out_dir)
        except (ConvertError, OSError) as exc:
            log.error('not converted: %s', exc)
            failed += 1
        else:
            log.info('converted: %s -> %s', path, dest)
    return 1 if failed else 0


def main(argv=None) -> int:
    """Run as `python -m rev80.convert_0x`; `rev80 convert-0x` is the same."""
    parser = argparse.ArgumentParser(
        prog='rev80 convert-0x', parents=[build_option_parser()],
        description='Copy Rev80 0.x data files into the format that Rev80 1.0 reads.')
    rev80.setup_logging()
    return run(parser.parse_args(argv))


if __name__ == '__main__':
    raise SystemExit(main())
