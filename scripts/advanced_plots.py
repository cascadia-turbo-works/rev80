"""Ad-hoc exploration of a *.h5 capture — run cell-by-cell in an editor that
supports "# %%" notebook cells (VS Code, Spyder, PyCharm, etc).

Reuses rev80.DataCollector for loading so filtering, mV->EU conversion, and
spectrum computation match what the GUI shows. Works with both file kinds:
  - a regular capture file  (/metadata, /frames, /trend)
  - a monitor session file  (/metadata, /monitor, /burst)
"""

# %% Setup
import json
from pathlib import Path

import h5py
import matplotlib.pyplot as plt

import rev80

DATAFILE = Path("<paste path here>")

# %% Load
with h5py.File(DATAFILE, "r") as f:
    is_monitor_session = "monitor" in f

collector = rev80.DataCollector()
if is_monitor_session:
    collector.load_monitor_session(DATAFILE)
else:
    collector.load_data(DATAFILE)


def _wire_sensors(col: rev80.DataCollector) -> None:
    for ch, sensor_cfg in col._loaded_channel_sensor_configs.items():
        if sensor_cfg:
            col.set_scope_sensor(ch, rev80.ScopeSensor.from_dict(sensor_cfg))


_wire_sensors(collector)

frames = list(collector.data["frame_cache"])  # list[dict[int, VibeSample]]
trend = collector.trend                       # dict[ch, {"rel_times": ..., "orders": (M,5)}]

print(f"{DATAFILE.name}: {'monitor session' if is_monitor_session else 'capture file'}, "
      f"{len(frames)} frame(s)")

# %% Metadata
with h5py.File(DATAFILE, "r") as f:
    file_version = int(f["metadata"].attrs.get("version", f["metadata"].attrs.get("file_version", 3)))

metadata = {
    "file_version": file_version,
    "notes": collector.notes,
    "acquisition": collector.config.to_dict(),
    "scope_sensors": collector._loaded_scope_sensors,       # {sensor_id: dict}
    "channels": collector._loaded_channel_sensor_configs,   # {ch: sensor dict}
}
print(json.dumps({k: v for k, v in metadata.items() if k not in ("scope_sensors", "channels")},
                  indent=2, default=str))

# %% Monitor — lightweight per-capture summary (timestamp, overall, peaks), no full data arrays
monitor = None
if is_monitor_session:
    monitor = []
    with h5py.File(DATAFILE, "r") as f:
        for key in sorted(f["monitor"].keys(), key=int):
            grp = f["monitor"][key]
            monitor.append({
                "index": int(key),
                "timestamp": grp.attrs.get("timestamp"),
                "rel_time": float(grp.attrs.get("rel_time", 0.0)),
                "samplerate": int(grp.attrs.get("samplerate", 0)),
                "status": grp.attrs.get("status"),
                "overall": json.loads(grp.attrs.get("overall_json", "{}")),
                "peaks": json.loads(grp.attrs.get("peaks_json", "{}")),
            })
    print(f"{len(monitor)} interval capture(s)")

# %% Burst — event list + on-demand loader (keeps `frames`/`trend` above untouched)
burst_list = []
if is_monitor_session:
    with h5py.File(DATAFILE, "r") as f:
        burst_list = json.loads(f["burst"].attrs.get("burst_list", "[]"))
    print(f"{len(burst_list)} burst event(s)")
    for b in burst_list:
        print(f"  {b['burst_id']}  trigger={b['trigger_type']}  t={b['rel_time']:.2f}s")


def load_burst(burst_id: str):
    """Load one burst event into its own DataCollector; returns (frames, trend)."""
    col = rev80.DataCollector()
    col.load_monitor_burst(DATAFILE, burst_id)
    _wire_sensors(col)
    return list(col.data["frame_cache"]), col.trend


# %% Example: time-domain plot of the latest frame
frame = frames[-1]
fig, axes = plt.subplots(len(frame), 1, sharex=True, squeeze=False)
for ax, (ch, sample) in zip(axes[:, 0], sorted(frame.items())):
    ax.plot(sample.time_vec, sample.data)
    ax.set_ylabel(f"Ch{ch} ({sample.unit})")
axes[-1, 0].set_xlabel("Time (s)")
fig.suptitle(next(iter(frame.values())).timestamp)
plt.show()

# %% Example: spectrum of the latest frame (via collector.process_sample — same path as the GUI)
frame = frames[-1]
fig, ax = plt.subplots()
for ch, sample in sorted(frame.items()):
    result = collector.process_sample(ch, sample)
    if result is not None:
        ax.plot(result.freq, result.spectrum, label=f"Ch{ch} ({result.unit})")
ax.set_xlabel("Frequency (Hz)")
ax.set_ylabel("Amplitude")
ax.legend()
plt.show()

# %% Example: trend overall vs time (column 2 = order 0, i.e. no integration/derivation)
fig, ax = plt.subplots()
for ch, td in trend.items():
    ax.plot(td["rel_times"], td["orders"][:, 2], label=f"Ch{ch}")
ax.set_xlabel("Time (s)")
ax.set_ylabel("Overall amplitude")
ax.legend()
plt.show()

# %% Example: load and plot the first burst event
if burst_list:
    b_frames, b_trend = load_burst(burst_list[0]["burst_id"])
    fig, ax = plt.subplots()
    for ch, td in b_trend.items():
        ax.plot(td["rel_times"], td["orders"][:, 2], label=f"Ch{ch}")
    ax.axvline(0, color="k", linestyle="--", label="trigger")
    ax.set_xlabel("Time (s, trigger = 0)")
    ax.set_ylabel("Overall amplitude")
    ax.legend()
    plt.show()
