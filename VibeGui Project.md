2025-01-23: presented my digiducer datacollection sript to Carmen

Need freq resolution calculator, and 

Requirements:

1. Date
2. Company info
3. Machine info, nameplate
   1. bearing types
   2. running rate
4. Time samples
5. Processed fault frequency data.
6. Luxury, startup, coastdown trend

- [ ] frequency range and binsize
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

- Create metadata file format with required fields
- Save data
- Allow multiple device/simulated device selection in config tab

### Active Features

- [ ] Add manual/auto axes scaling
- [ ] Add freq binsize and limits
- [ ] Replace fft process with endaq tools
- [ ] Save data!

### BUGS

- [ ] Isolate dataprocessing from VibrationDevice
- [ ] multiple stream start/stop results in 'device not found'

### Complete

- Sample data from digiducer
- Create digiducer simulator for offline production
- Capture and display data in GUI
  - [x] Stream start+stop and single capture.
  - [x] Time
  - [x] FFT
  - [ ] Trend - later
