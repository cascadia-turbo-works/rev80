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
- [ ] GUI should run a thread that watches collector queue for samples.. rather than passing samples directly.
- [ ] Make better use of queue
  - Make gui thread to continuously watch collector queue and consume data to plot.. rather than collector callbacks

### Active Features

- [ ] Create metadata file format with required fields
- [ ] Set equipment running rate and visualize octaves
- [x] Detect peaks!

### BUGS

- none!


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


## 12/30/26 Carmen meet

Looks clean!

Critical

- Overall viberation energy IPS zero to peak (0-p)
  - Plot trend over time
- Fix units - IPS is large by around 200x

Future

- Prox probe only need to integrate one sensor.

## DAQ System

### option 1

- [ni-9239 DAQ](https://www.ni.com/en-us/shop/model/ni-9239.html) DAQ
  - 1,428.00
  - Maximum Number of Differential Analog Input Channels: 4
  - Analog Input Voltage Range: -10 V to 10 V
  - Enclosed: Yes
  - Analog Input Resolution: 24 bits
  - Maximum Sample Rate: 50 kS/s/ch
- [cDAQ9181](https://www.ni.com/en-us/shop/model/cdaq-9181.html) Chassis
  - $ 675.00
  - Bus Connector: Ethernet
  - Operating Temperature Range: 0 °C to 55 °C
  - Slot Count: 1
  - Onboard Trigger: No
  - Synchronization Enabled: No
  - Counter included on chassis but we need a multifunction card to access it.

### Option 2

- [cDAQ-SV1101](https://www.ni.com/en-us/shop/model/cdaq-sv1101-bundle.html) Bundle
  - $ 2,916.00
  - 1-Slot, 4-Channel, 51.2 kS/s/channel, �5 V, CompactDAQ Sound and Vibration Measurement Bundle
  - Fails voltage range, but we could use an attenuator?
 
### Option 3
 
- [MCC USB-1808X](https://digilent.com/shop/mcc-usb-1808x-high-speed-high-precision-simultaneous-usb-daq-device/) High-Speed, High-Precision, Simultaneous USB DAQ Device
  - $989.00
  - 8 SE/8 DIFF simultaneous analog inputs
  - 18-bit resolution
  - 200 kS/s/ch sample rate
  - ±10 V, ±5 V, 0-10 V, 0-5 V input ranges
  - Two 16-bit analog outputs
  - Four digital I/O
  - Two counter inputs
  - Two quadrature encoder inputs
  - Two timer outputs
  - No external power required
- [MCC 172](https://digilent.com/shop/mcc-172-iepe-measurement-daq-hat-for-raspberry-pi/) IEPE Measurement DAQ HAT for Raspberry Pi]
  - $399.00

### option 4

- [MCC USB-1608FS-Plus](https://digilent.com/shop/mcc-usb-1608fs-plus-simultaneous-usb-daq-device/): Simultaneous USB DAQ Device
  = $459.00

## Meeting 2026-01-11

DAQ: Purchased Option 4

Vibegui:

- added overall 0-P vibration (acc and vel)
  - Add trend should be easy now.
  - #TODO confirm overall values are right. Sometimes OVERALL is greater than single peaks
- Bin selecter behaves poorly
- Changed timestamp format in sample.save to replace ':' (invalid on FAT32 system)
- UI/UX, language and jargon should match Alta
- Demo screenshots for website

## 2026 - 03 -18 TODO

- Multi channel
  - Toggle on and off channel display with 2+ channels
  - Two channel phase relationship
- Time domain window, ex zoom to 5ms of time domain
- Track down velocity integration low freq noise
- Windows functional
  - Package exe

## 2026 - 03 - 25

- Add 0P, PP or RMS to sensor setup. 
- Acq setting lead to long acq times. Examine
- Displaying wrong bins in spectrum setup
