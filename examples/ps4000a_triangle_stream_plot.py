#
# PicoScope 4000A — Triangle Wave Generator + Streaming Capture
#
# Generates a 500 Hz triangle wave at 1.41 V amplitude (2.82 Vpp) with a +3 V DC offset
# on the built-in signal generator, then streams Channel A over a 100 ms capture window
# (50 complete cycles at 500 Hz). Results are written to triangle_wave.html using Plotly.
#
# Requirements:
#   pip install picosdk numpy plotly
#
# Timebase:
#   Total capture window : 100 ms
#   Sample interval      : 20 µs  →  50 kHz sample rate
#   Total samples        : 5 000  (100 ms / 20 µs)
#   Samples per cycle    : 100    (2 ms period / 20 µs)
#

import ctypes
import numpy as np
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from scipy.signal import welch, find_peaks, peak_prominences
from picosdk.ps4000a import ps4000a as ps
from picosdk.functions import adc2mV, assert_pico_ok
import time

# ---------------------------------------------------------------------------
# Constants — edit here to adjust behaviour
# ---------------------------------------------------------------------------
SAMPLE_INTERVAL_US   = 20          # µs between ADC samples (20 µs → 50 kHz)
CAPTURE_WINDOW_MS    = 100         # total capture duration in ms
TOTAL_SAMPLES        = int(CAPTURE_WINDOW_MS * 1000 / SAMPLE_INTERVAL_US)  # 5000
BUFFER_SIZE          = 500         # samples per driver-registered rolling buffer
NUM_BUFFERS          = TOTAL_SAMPLES // BUFFER_SIZE  # 10

SIGGEN_PKTOPK_UV     = 1_000   # 2 × 0.5 V = 1.0 Vpp in µV
# PS4000A siggen output is clamped to ±2 V.  The constraint is:
#   |offsetVoltage| + pkToPk/2 ≤ 2,000,000 µV
# 1,400,000 + 500,000 = 1,900,000 µV ≤ 2,000,000 µV ✓
SIGGEN_OFFSET_UV     = 1_400_000   # +1.4 V DC offset in µV
SIGGEN_FREQ_HZ       = 500.0       # triangle wave frequency

CHANNEL_RANGE        = 8   # PS4000A_5V — range index passed as plain int to SDK and adc2mV
OUTPUT_HTML          = "triangle_wave.html"

# ---------------------------------------------------------------------------
# Open device
# ---------------------------------------------------------------------------
status   = {}
chandle  = ctypes.c_int16()

status["openunit"] = ps.ps4000aOpenUnit(ctypes.byref(chandle), None)

try:
    assert_pico_ok(status["openunit"])
except Exception:
    powerstate = status["openunit"]
    if powerstate == 282:
        status["changePowerSource"] = ps.ps4000aChangePowerSource(chandle, 282)
    elif powerstate == 286:
        status["changePowerSource"] = ps.ps4000aChangePowerSource(chandle, 286)
    else:
        raise
    assert_pico_ok(status["changePowerSource"])

# ---------------------------------------------------------------------------
# Signal generator — triangle wave, 500 Hz, 1.41 V amplitude, +3 V offset
# ---------------------------------------------------------------------------
wavetype      = ps.PS4000A_WAVE_TYPE['PS4000A_TRIANGLE']
sweepType     = ps.PS4000A_SWEEP_TYPE['PS4000A_UP']
triggertype   = ps.PS4000A_SIGGEN_TRIG_TYPE['PS4000A_SIGGEN_RISING']
triggerSource = ps.PS4000A_SIGGEN_TRIG_SOURCE['PS4000A_SIGGEN_NONE']
extInThreshold = ctypes.c_int16(0)

status["setSigGen"] = ps.ps4000aSetSigGenBuiltIn(
    chandle,
    SIGGEN_OFFSET_UV,   # offsetVoltage (µV)
    SIGGEN_PKTOPK_UV,   # pkToPk (µV)
    wavetype,
    SIGGEN_FREQ_HZ,     # startFrequency
    SIGGEN_FREQ_HZ,     # stopFrequency (same → no sweep)
    0,                  # increment
    1,                  # dwellTime
    sweepType,
    0,                  # operation
    0,                  # shots
    0,                  # sweeps
    triggertype,
    triggerSource,
    extInThreshold,
)
assert_pico_ok(status["setSigGen"])
print(f"Signal generator active: triangle wave {SIGGEN_FREQ_HZ} Hz, "
      f"{SIGGEN_PKTOPK_UV / 1e6:.3f} Vpp, +{SIGGEN_OFFSET_UV / 1e6:.3f} V offset")

# ---------------------------------------------------------------------------
# Channel A — AC coupling, 5 V range
# ---------------------------------------------------------------------------
status["setChA"] = ps.ps4000aSetChannel(
    chandle,
    ps.PS4000A_CHANNEL['PS4000A_CHANNEL_A'],
    1,                                          # enabled
    ps.PS4000A_COUPLING['PS4000A_AC'],          # AC coupling
    CHANNEL_RANGE,
    0.0,                                        # analogue offset
)
assert_pico_ok(status["setChA"])

# Disable Channel B (not needed)
status["setChB"] = ps.ps4000aSetChannel(
    chandle,
    ps.PS4000A_CHANNEL['PS4000A_CHANNEL_B'],
    0,                                          # disabled
    ps.PS4000A_COUPLING['PS4000A_DC'],
    7,                                          # PS4000A_2V — range index, channel is disabled so value is nominal
    0.0,
)
assert_pico_ok(status["setChB"])

# ---------------------------------------------------------------------------
# Streaming buffers — Channel A only
# ---------------------------------------------------------------------------
bufferAMax = np.zeros(shape=BUFFER_SIZE, dtype=np.int16)

status["setDataBuffersA"] = ps.ps4000aSetDataBuffers(
    chandle,
    ps.PS4000A_CHANNEL['PS4000A_CHANNEL_A'],
    bufferAMax.ctypes.data_as(ctypes.POINTER(ctypes.c_int16)),
    None,                                       # no min buffer
    BUFFER_SIZE,
    0,                                          # memory segment
    ps.PS4000A_RATIO_MODE['PS4000A_RATIO_MODE_NONE'],
)
assert_pico_ok(status["setDataBuffersA"])

# ---------------------------------------------------------------------------
# Start streaming
# ---------------------------------------------------------------------------
sampleInterval = ctypes.c_int32(SAMPLE_INTERVAL_US)
sampleUnits    = ps.PS4000A_TIME_UNITS['PS4000A_US']

status["runStreaming"] = ps.ps4000aRunStreaming(
    chandle,
    ctypes.byref(sampleInterval),
    sampleUnits,
    0,              # maxPreTriggerSamples
    TOTAL_SAMPLES,
    1,              # autoStopOn
    1,              # downsampleRatio
    ps.PS4000A_RATIO_MODE['PS4000A_RATIO_MODE_NONE'],
    BUFFER_SIZE,
)
assert_pico_ok(status["runStreaming"])

actualSampleInterval_us = sampleInterval.value
print(f"Streaming at {actualSampleInterval_us} µs sample interval "
      f"({1e6 / actualSampleInterval_us:.0f} Hz sample rate), "
      f"capturing {TOTAL_SAMPLES} samples over {CAPTURE_WINDOW_MS} ms")

# ---------------------------------------------------------------------------
# Collect streamed data via callback
# ---------------------------------------------------------------------------
bufferCompleteA = np.zeros(shape=TOTAL_SAMPLES, dtype=np.int16)
nextSample      = 0
autoStopOuter   = False
wasCalledBack   = False


def streaming_callback(handle, noOfSamples, startIndex, overflow,
                       triggerAt, triggered, autoStop, param):
    global nextSample, autoStopOuter, wasCalledBack
    wasCalledBack = True
    destEnd   = nextSample + noOfSamples
    sourceEnd = startIndex + noOfSamples
    bufferCompleteA[nextSample:destEnd] = bufferAMax[startIndex:sourceEnd]
    nextSample += noOfSamples
    if autoStop:
        autoStopOuter = True


cFuncPtr = ps.StreamingReadyType(streaming_callback)

while nextSample < TOTAL_SAMPLES and not autoStopOuter:
    wasCalledBack = False
    status["getStreamingLatestValues"] = ps.ps4000aGetStreamingLatestValues(
        chandle, cFuncPtr, None
    )
    if not wasCalledBack:
        time.sleep(0.001)

print(f"Capture complete: {nextSample} samples collected.")

# ---------------------------------------------------------------------------
# Convert ADC counts → millivolts
# ---------------------------------------------------------------------------
maxADC = ctypes.c_int16()
status["maximumValue"] = ps.ps4000aMaximumValue(chandle, ctypes.byref(maxADC))
assert_pico_ok(status["maximumValue"])

adc2mVChA = adc2mV(bufferCompleteA, CHANNEL_RANGE, maxADC)

# Time axis in milliseconds
time_ms = np.linspace(0, CAPTURE_WINDOW_MS, TOTAL_SAMPLES)

# ---------------------------------------------------------------------------
# Stop and close device
# ---------------------------------------------------------------------------
status["stop"]  = ps.ps4000aStop(chandle)
assert_pico_ok(status["stop"])
status["close"] = ps.ps4000aCloseUnit(chandle)
assert_pico_ok(status["close"])
print("Device closed.")

# ---------------------------------------------------------------------------
# Frequency analysis — Welch PSD, 10 windows, 50% overlap
# ---------------------------------------------------------------------------
sample_rate_hz  = 1e6 / SAMPLE_INTERVAL_US          # 50 000 Hz
N_WELCH_WINDOWS = 10
# Derive nperseg so that exactly N_WELCH_WINDOWS segments fit at 50% overlap:
#   n = 1 + (N - nperseg) / step,  step = nperseg/2
#   → nperseg = 2*N / (n+1)
nperseg  = (2 * TOTAL_SAMPLES) // (N_WELCH_WINDOWS + 1)
if nperseg % 2 != 0:
    nperseg -= 1                                     # keep even for FFT efficiency
noverlap = nperseg // 2                              # 50% overlap

freqs, psd = welch(
    np.array(adc2mVChA, dtype=np.float64),
    fs=sample_rate_hz,
    nperseg=nperseg,
    noverlap=noverlap,
    window="hann",
    scaling="density",
)

dF    = freqs[1] - freqs[0]                         # frequency resolution (Hz)
nbins = len(freqs)
print(f"Welch PSD: nperseg={nperseg}, noverlap={noverlap}, dF={dF:.2f} Hz, {nbins} bins")

# Top-5 peaks by prominence
peaks, _   = find_peaks(psd, prominence=0)
proms      = peak_prominences(psd, peaks)[0]
top5_idx   = peaks[np.argsort(proms)[::-1][:5]]
top5_idx   = top5_idx[np.argsort(freqs[top5_idx])]  # re-sort by frequency

# ---------------------------------------------------------------------------
# Plotly subplots — spectrum (top 3/4) + time trace (bottom 1/4)
# ---------------------------------------------------------------------------
fig = make_subplots(
    rows=2, cols=1,
    row_heights=[0.75, 0.25],
    vertical_spacing=0.10,
    subplot_titles=("Power Spectral Density", "Time Trace — Channel A"),
)

# Spectrum line
fig.add_trace(go.Scatter(
    x=freqs,
    y=psd,
    mode="lines",
    name="PSD",
    line=dict(color="#1f77b4", width=1),
    hovertemplate="<b>%{x:.1f} Hz</b><br>PSD: %{y:.4g} mV²/Hz<extra></extra>",
), row=1, col=1)

# Peak markers with frequency + amplitude tooltips
fig.add_trace(go.Scatter(
    x=freqs[top5_idx],
    y=psd[top5_idx],
    mode="markers",
    name="Top 5 peaks",
    marker=dict(color="red", size=10, symbol="circle-open", line=dict(width=2)),
    customdata=np.stack([freqs[top5_idx], psd[top5_idx]], axis=1),
    hovertemplate=(
        "<b>Peak</b><br>"
        "Frequency: %{customdata[0]:.1f} Hz<br>"
        "PSD: %{customdata[1]:.4g} mV²/Hz"
        "<extra></extra>"
    ),
), row=1, col=1)

# Time trace
fig.add_trace(go.Scatter(
    x=time_ms,
    y=list(adc2mVChA),
    mode="lines",
    name="Channel A",
    line=dict(color="#2ca02c", width=1),
    hovertemplate="<b>%{x:.3f} ms</b><br>%{y:.1f} mV<extra></extra>",
), row=2, col=1)

fig.update_layout(
    title=dict(
        text=(
            "PicoScope 4000A — 500 Hz Triangle Wave (Channel A, AC coupled)<br>"
            f"<sup>Welch PSD · {N_WELCH_WINDOWS} windows · 50% overlap · "
            f"dF = {dF:.2f} Hz · {nbins} bins</sup>"
        ),
        font=dict(size=16),
    ),
    xaxis =dict(title="Frequency (Hz)"),
    xaxis2=dict(title="Time (ms)", range=[0, CAPTURE_WINDOW_MS]),
    yaxis =dict(title="PSD (mV²/Hz)"),
    yaxis2=dict(title="Voltage (mV)"),
    hovermode="closest",
    template="plotly_white",
    legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
)

fig.write_html(OUTPUT_HTML)
print(f"Plot saved to {OUTPUT_HTML}")

print(status)
