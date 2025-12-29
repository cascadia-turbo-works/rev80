2025-01-23: presented my digiducer datacollection sript to Carmen

Need freq resolution calculator, and 

Requirements:

1. Date
2. Company info
3. Machine info, nameplate
   1. bearing types
   2. running rate
4. Time samples
5
5. Processed fault frequency data
6. Luxury, startup, coastdown trend

- [x] frequency range and binsize
- [x] normalize fft to IPS, or g
  - velocity is better than acc
- [ ] smoothing
- [ ] interactive peak inspection
- [ ] calculate top 10 peaks
- [ ] markers for mupliples of running speed
- [ ] markers for bearing FF

NOTE: look into existing vibe analysis apps

- There aren't many great options out there
- VibeAnalyze app, $999. Very nice data recording.

Data capture file contents

- metadata.yaml - contains capture metadata
- time.pkl - recorded data
- fft.pkl - processed fft data
- trend.pkl - processed trend data
- ring.pkl - resonance testing ring data.
- zipped into .vibe file format

[prox probes](https://www.balluff.com/en-us/blog/the-basic-operating-principle-of-an-inductive-proximity-sensor)

## Tasks

### Upcomming

- [ ] Implement RMS trend over recording window
- [ ] Highpass filter sample kill DC below 10hz
- [ ] TREND
- [ ] Make better use of queue
  - Make gui thread to continuously watch collector queue and consume data to plot.. rather than collector callbacks

### Active Features

- [ ] Create metadata file format with required fields
- [ ] Set equipment running rate and visualize octaves
- [x] Detect peaks!

### BUGS

- full crash when Digiducer is unplugged during connection.
  - It doesn't seem like I can catch this error before it crashes the window. See log:

```bash
2025-11-20 20:48:18,362 - vibe.gui - INFO - Starting sensor stream with Digiducer_333D05 (sn:083938, id:7)
Expression 'alsa_snd_pcm_prepare( stream->capture.pcm )' failed in 'src/hostapi/alsa/pa_linux_alsa.c', line: 2932
Expression 'AlsaStart( stream, 0 )' failed in 'src/hostapi/alsa/pa_linux_alsa.c', line: 4244
Expression 'alsa_snd_pcm_drop( stream->capture.pcm )' failed in 'src/hostapi/alsa/pa_linux_alsa.c', line: 3046
2025-11-20 20:48:27,478 - vibe.gui - INFO - Cleanup app assets
python: src/os/unix/pa_unix_util.c:510: PaUnixMutex_Terminate: Assertion `0 == paUtilErr_' failed.
```


### Complete

- [x] Save data!
- [x] Isolate dataprocessing from DataCollector
- [x] Allow multiple device/simulated device selection in config tab
- [x] Add manual/auto axes scaling - Why is this so haaard?!?
- [x] Add freq binsize and limits
- [x] Sample data from digiducer
- [x] Create digiducer simulator for offline testing
- [x] Capture and display data in GUI
  - [x] Stream start+stop and single capture.
  - [x] Time
  - [x] FFT
- [x] add data loader to gui
- [x] Improve file saving with filename and path specification.
- [x] Replace fft process with scipy
  - [x] Whole spectrum or specify freq window
- [x] Highlight top  peaks
  - Alta

## 11/25/26 meet with Carmen

- [x] switch between m/s and m/s/s in freq domain. HF peaks are suppressed in velocity spectrum
- Goal is to put the most useful features of Rev's more sophistocated vibe box 
- Deployment
  - IT police won't allow app on company computers

- Trend analysis
  - Inches per second zero to peak
  - option for RMS

- Download ENDAQ Free software

PHASE 1:

- [x] development so far!
- $2k

PHASE 2:

- polish and deploy to windows
- $1000

PHASE 2:

- Integrate BNC DAQ for prox probes!
- $1000

PHASE 3:

- Sales!

FUTURE:

- two sensors simulaneous to show phasing from two sample points.
- integrate proxprobes with DAQ?
  - Need to find DAQ at low cost for 4 channel BNC
- Sexy web portal for data sharing.
