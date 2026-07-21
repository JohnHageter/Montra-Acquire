"""DAQ (data-acquisition) abstraction layer.

Provides DAQInterface (abstract) and two concrete implementations:
  SimulatedDAQInterface — no-op backend used when nidaqmx is not installed or
      no hardware is present.  Logs each call so scripts can be tested without
      physical hardware.
  NidaqmxDAQInterface   — real NI-DAQ backend via the nidaqmx package.

make_daq(device) returns the appropriate implementation: if device is empty or
nidaqmx is not installed, the simulated backend is returned; otherwise the real
backend is used.  Callers never need to import nidaqmx directly.

All implementations must be thread-safe — script commands call DAQ methods from
the acquisition worker thread while the UI runs on the main thread.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Optional

import numpy as np


class DAQInterface(ABC):
    """Abstract DAQ backend. Implementations must be thread-safe."""

    @abstractmethod
    def digital_out(self, channel: str, value: bool) -> None:
        """Set a digital output line high (True) or low (False)."""

    @abstractmethod
    def analog_waveform(self, channel: str, data: np.ndarray, rate: float) -> None:
        """Write a finite analog waveform. Blocks until complete."""

    @abstractmethod
    def close(self) -> None:
        """Release all hardware resources."""


class SimulatedDAQInterface(DAQInterface):
    """No-op backend used when no DAQ hardware is present or nidaqmx is not installed."""

    def __init__(self, log_fn=None) -> None:
        self._log = log_fn or (lambda msg: print(f"[DAQ SIM] {msg}"))

    def digital_out(self, channel: str, value: bool) -> None:
        self._log(f"digital_out  {channel} = {int(value)}")

    def analog_waveform(self, channel: str, data: np.ndarray, rate: float) -> None:
        self._log(f"analog_waveform  {channel}  {len(data)} samples @ {rate:.1f} Hz")

    def close(self) -> None:
        pass


class NIDaqInterface(DAQInterface):
    """
    NI-DAQmx backend via the nidaqmx package.
    Raises ImportError on construction if nidaqmx is not installed.
    """

    def __init__(self, device: str = "Dev1", log_fn=None) -> None:
        import nidaqmx  # intentional: raises ImportError if not installed
        self._nidaqmx = nidaqmx
        self._device = device
        _log = log_fn or (lambda msg: None)

        # Log the driver version so users know what they're running against.
        # NI-DAQmx runtime >= 14.0 (2014) is required by the nidaqmx Python package.
        # NI MAX is only a management GUI — the driver version is what matters.
        try:
            import nidaqmx.system as _sys
            dv = _sys.System.local().driver_version
            version_str = f"{dv.major_version}.{dv.minor_version}.{dv.update_version}"
            _log(f"NI-DAQmx driver: {version_str}")
            if dv.major_version < 14:
                _log(
                    "WARNING: NI-DAQmx driver < 14.0 detected. "
                    "The nidaqmx Python package requires driver >= 14.0. "
                    "Update the NI-DAQmx runtime at ni.com/downloads — "
                    "NI MAX itself does not need to match; only the runtime driver matters."
                )
        except Exception:
            pass  # nidaqmx < 0.6 does not expose driver_version

    def digital_out(self, channel: str, value: bool) -> None:
        with self._nidaqmx.Task() as task:
            task.do_channels.add_do_chan(channel)
            task.write(value)

    def analog_waveform(self, channel: str, data: np.ndarray, rate: float) -> None:
        with self._nidaqmx.Task() as task:
            task.ao_channels.add_ao_voltage_chan(channel)
            task.timing.cfg_samp_clk_timing(
                rate,
                sample_mode=self._nidaqmx.constants.AcquisitionType.FINITE,
                samps_per_chan=len(data),
            )
            task.write(data.tolist(), auto_start=True)
            task.wait_until_done()

    def close(self) -> None:
        pass  # tasks are managed with context managers


def make_daq(device: str = "", log_fn=None) -> DAQInterface:
    """
    Return an NIDaqInterface if nidaqmx is installed and *device* is non-empty,
    otherwise return a SimulatedDAQInterface that logs all operations.
    """
    if not device.strip():
        return SimulatedDAQInterface(log_fn)
    try:
        return NIDaqInterface(device, log_fn=log_fn)
    except ImportError as exc:
        sim = SimulatedDAQInterface(log_fn)
        if log_fn:
            log_fn(f"nidaqmx import failed — DAQ commands will be simulated (device={device!r})")
            log_fn(f"  ImportError: {exc}")
        return sim
    except Exception as exc:
        sim = SimulatedDAQInterface(log_fn)
        if log_fn:
            log_fn(f"nidaqmx failed to initialize — DAQ commands will be simulated (device={device!r})")
            log_fn(f"  Error ({type(exc).__name__}): {exc}")
        return sim


def generate_waveform(
    kind: str,
    freq: float,
    amp: float,
    duration: float,
    sample_rate: float = 10_000.0,
) -> np.ndarray:
    """Generate a numpy float64 waveform array for DAQ analog output."""
    n = max(1, int(sample_rate * duration))
    t = np.linspace(0, duration, n, endpoint=False)
    kind = kind.lower()

    if kind == "sine":
        return (amp * np.sin(2 * np.pi * freq * t)).astype(np.float64)

    if kind == "square":
        try:
            from scipy import signal as sp_signal
            return (amp * sp_signal.square(2 * np.pi * freq * t)).astype(np.float64)
        except ImportError:
            # Fallback: manual square wave
            return (amp * np.sign(np.sin(2 * np.pi * freq * t))).astype(np.float64)

    if kind == "ramp":
        period = 1.0 / max(freq, 1e-9)
        return (amp * ((t % period) / period)).astype(np.float64)

    return np.zeros(n, dtype=np.float64)
