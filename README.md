# Montra-Acquire

Scripted camera acquisition software for behavioral experiments. Controls cameras (IDS, FLIR, OpenCV), NI-DAQ hardware, and records video via plain-text `.acq` protocol scripts.

## Features

- Live camera preview with watch-window cropping
- Script engine for automating multi-trial recording sessions
- NI-DAQ digital/analog output (TTL pulses, waveforms)
- Timelapse recording
- Acquisition log (JSON + H5) written automatically after each session

## Requirements

- Python 3.10+
- [PySide6](https://pypi.org/project/PySide6/), [OpenCV](https://pypi.org/project/opencv-python/), [h5py](https://pypi.org/project/h5py/), [numpy](https://pypi.org/project/numpy/)
- IDS peak SDK (for IDS cameras)
- NI-DAQmx runtime (for DAQ hardware)

## Running from a release

Download and unzip `Montra-Acquire.zip` from the [Releases](../../releases) page and run `Montra-Acquire.exe` — no Python or conda required.

## Installation (development)

```bash
conda create -n montra-acquire python=3.10
conda activate montra-acquire
pip install -e montra-lib
pip install -e montra-acquire
python montra-acquire/main_acquisition.py
```

## Protocol scripts

`.acq` scripts are loaded via the script editor in the UI. See [`montra-acquire/examples/protocols/`](montra-acquire/examples/protocols/) for examples and a full command reference.

## Building a standalone executable

```bash
python build_exe.py          # produces dist/Montra-Acquire/ and Montra-Acquire.zip
```
