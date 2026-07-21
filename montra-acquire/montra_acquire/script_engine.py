"""
Acquisition Protocol DSL — parser + executor.

Grammar (.acq files):
    # comments
    DEF name:
        <commands>
    END
    SET key = value
    LOAD_ROIS <name>
    CAMERA <backend> [index]        # open camera (Test / OpenCV / IDS), index default 0
    WATCH <x> <width> <y> <height>  # set camera watch window
    OUTPUTDIR <path>                # set output directory for all saved files
    DELAY <seconds>
    RECORD <seconds>
    SNAPSHOT                        # snap without saving (updates last_frame / preview)
    SNAPSHOT <prefix>               # save PNG as <prefix>_<timestamp>.png in output dir
    SNAPSHOT ref                    # update live preview reference frame
    SNAPSHOT bg <frames> <blur>     # build background image from N frames (saves background.png)
    ELAPSE                          # log elapsed time since script start
    COUNT                           # increment internal counter (starting from 0) and log it
    WAITKEY <key>                   # space, enter, escape, or any single char
    LOG "message"
    REPEAT <n>:
        <commands>
    END
    CALL <name>
    DAQ_DIGITAL <channel>, <0|1>
    DAQ_ANALOG  <channel>, <waveform>, <freq>, <amp>, <duration>
    DAQ_PULSE   <channel>, <duration_s>
    TIMELAPSE <n_frames> <interval_s> [playback_fps]
              # capture one frame every interval_s and write all frames into a
              # single mp4. playback_fps controls how fast the final video plays
              # back (default 24). Example: TIMELAPSE 60 60.0 produces a 1-hour
              # timelapse (1 frame/min) that plays back in 2.5 seconds at 24 fps.

String interpolation:
    OUTPUTDIR, SET value, LOG, and SNAPSHOT prefix arguments support {variable}
    substitution.  Available variables:
        {iter}      1-based index of the current REPEAT iteration (0 outside any REPEAT)
        {count}     current COUNT counter value
        {video}     current video file index (increments after each successful RECORD)
        {subject}   current SET subject value
        {condition} current SET condition value
        {replicate} current SET replicate value

    Example — per-trial subdirectory with auto-numbered trials:
        REPEAT 4:
            OUTPUTDIR D:\\Data\\trial_{iter}
            SET condition = white_light
            RECORD 30
            SET condition = dark
            RECORD 30
        END
"""

from __future__ import annotations

import json
import os
import re
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional, Tuple

import cv2

from montra_acquire.daq import make_daq, generate_waveform



@dataclass
class Command:
    kind: str
    args: List[str] = field(default_factory=list)
    body: List["Command"] = field(default_factory=list)
    lineno: int = 0


class ScriptSyntaxError(Exception):
    def __init__(self, message: str, lineno: int = 0) -> None:
        super().__init__(f"Line {lineno}: {message}")
        self.lineno = lineno


@dataclass
class ScriptContext:
    camera_worker: Any = None          # CameraWorker proxy (thread-safe)
    daq: Any = None                    # DAQInterface instance or None; auto-created by DAQ_* commands
    app_paths: Any = None              # AppPaths class; needed for LOAD_ROIS

    output_dir: Optional[str] = None
    video_counter: int = 0
    count: int = 0                     # general-purpose counter, incremented by COUNT

    # Experiment metadata — drive filename prefix and JSON attributes
    subject: str = ""
    condition: str = ""
    replicate: int = 1
    skip_recording: bool = False       # when True, RECORD becomes a DELAY

    # WAITKEY synchronisation — set/cleared by AcquisitionTab on key press
    key_event: threading.Event = field(default_factory=threading.Event)
    last_key: str = ""

    # Snap event — set by CameraWorker when an async snap-to-file completes
    snap_event: threading.Event = field(default_factory=threading.Event)

    log_callback: Optional[Callable[[str], None]] = None
    waitkey_callback: Optional[Callable[[], None]] = None

    # Session-level recording log — consolidated into acquisition_log.json at script end
    session_log: list = field(default_factory=list)
    session_start: str = ""

    # Camera settings at script start — written to acquisition.h5
    camera_fps: float = 0.0
    camera_exposure: float = 0.0
    camera_gain: float = 0.0
    camera_width: int = 0
    camera_height: int = 0


# ── Parser ────────────────────────────────────────────────────────────────────

def _tokenise(line: str) -> List[str]:
    """Split a line into tokens; quoted strings are kept as single tokens."""
    return [m.group() for m in re.finditer(r'"[^"]*"|\'[^\']*\'|\S+', line)]


def parse(text: str) -> Tuple[Dict[str, List[Command]], List[Command]]:
    """
    Parse script text.

    Returns:
        (functions, top_level_commands)
        functions: dict mapping function name → command list (hoisted)
    """
    # Strip comments and blanks, preserving 1-based line numbers.
    processed: List[Tuple[int, str]] = []
    for i, raw in enumerate(text.splitlines(), start=1):
        stripped = raw.split("#")[0].strip()
        if stripped:
            processed.append((i, stripped))

    functions: Dict[str, List[Command]] = {}

    def parse_block(pos: int, stop_at_end: bool) -> Tuple[List[Command], int]:
        cmds: List[Command] = []
        while pos < len(processed):
            lineno, line = processed[pos]
            tokens = _tokenise(line)
            if not tokens:
                pos += 1
                continue

            keyword = tokens[0].upper()

            if keyword == "END":
                if stop_at_end:
                    return cmds, pos + 1
                raise ScriptSyntaxError("Unexpected END", lineno)

            if keyword == "DEF":
                if len(tokens) < 2:
                    raise ScriptSyntaxError("DEF requires a function name", lineno)
                fname = tokens[1].rstrip(":")
                if not re.match(r'^[A-Za-z_]\w*$', fname):
                    raise ScriptSyntaxError(f"Invalid function name: {fname!r}", lineno)
                body, pos = parse_block(pos + 1, stop_at_end=True)
                functions[fname] = body
                continue

            if keyword == "REPEAT":
                if len(tokens) < 2:
                    raise ScriptSyntaxError("REPEAT requires a count", lineno)
                try:
                    n = int(tokens[1].rstrip(":"))
                except ValueError:
                    raise ScriptSyntaxError(
                        f"REPEAT count must be an integer, got {tokens[1]!r}", lineno
                    )
                body, pos = parse_block(pos + 1, stop_at_end=True)
                cmds.append(Command("REPEAT", args=[str(n)], body=body, lineno=lineno))
                continue

            cmd = _parse_single(keyword, tokens[1:], lineno)
            cmds.append(cmd)
            pos += 1

        if stop_at_end:
            last_lineno = processed[-1][0] if processed else 0
            raise ScriptSyntaxError("Missing END", last_lineno)
        return cmds, pos

    top_level, _ = parse_block(0, stop_at_end=False)
    return functions, top_level


def _parse_single(keyword: str, args: List[str], lineno: int) -> Command:
    def need(n: int) -> None:
        if len(args) < n:
            raise ScriptSyntaxError(
                f"{keyword} requires {n} argument(s), got {len(args)}", lineno
            )

    def csv_args() -> List[str]:
        """Re-join args then split on commas to handle 'a, b, c' → ['a','b','c']."""
        return [p.strip() for p in " ".join(args).split(",") if p.strip()]

    kw = keyword.upper()

    if kw == "SET":
        joined = " ".join(args)
        m = re.match(r'^(\w+)\s*=\s*(.+)$', joined)
        if not m:
            raise ScriptSyntaxError("SET syntax: SET key = value", lineno)
        return Command("SET", args=[m.group(1).strip(), m.group(2).strip()], lineno=lineno)

    if kw == "LOAD_ROIS":
        need(1)
        return Command("LOAD_ROIS", args=[args[0]], lineno=lineno)

    if kw == "CAMERA":
        need(1)
        backend = args[0].strip("\"'")
        index = 0
        if len(args) > 1:
            try:
                index = int(args[1])
            except ValueError:
                raise ScriptSyntaxError(
                    f"CAMERA index must be an integer, got {args[1]!r}", lineno
                )
        return Command("CAMERA", args=[backend, str(index)], lineno=lineno)

    if kw == "WATCH":
        if len(args) < 4:
            raise ScriptSyntaxError("WATCH requires: x width y height", lineno)
        for a in args[:4]:
            try:
                int(a)
            except ValueError:
                raise ScriptSyntaxError(
                    f"WATCH arguments must be integers, got {a!r}", lineno
                )
        return Command("WATCH", args=args[:4], lineno=lineno)

    if kw == "OUTPUTDIR":
        need(1)
        path = " ".join(args).strip("\"'")
        return Command("OUTPUTDIR", args=[path], lineno=lineno)

    if kw == "ELAPSE":
        return Command("ELAPSE", lineno=lineno)

    if kw == "COUNT":
        return Command("COUNT", lineno=lineno)

    if kw == "DELAY":
        need(1)
        try:
            float(args[0])
        except ValueError:
            raise ScriptSyntaxError(f"DELAY requires a number, got {args[0]!r}", lineno)
        return Command("DELAY", args=[args[0]], lineno=lineno)

    if kw == "RECORD":
        need(1)
        try:
            float(args[0])
        except ValueError:
            raise ScriptSyntaxError(
                f"RECORD requires a duration in seconds, got {args[0]!r}", lineno
            )
        return Command("RECORD", args=[args[0]], lineno=lineno)

    if kw == "SNAPSHOT":
        if not args:
            return Command("SNAPSHOT", args=[], lineno=lineno)
        first = args[0].strip("\"'").lower()
        if first == "ref":
            return Command("SNAPSHOT", args=["ref"], lineno=lineno)
        elif first == "bg":
            return Command("SNAPSHOT", args=["bg"] + args[1:], lineno=lineno)
        else:
            return Command("SNAPSHOT", args=[args[0].strip("\"'")], lineno=lineno)

    if kw == "WAITKEY":
        need(1)
        return Command("WAITKEY", args=[args[0].lower()], lineno=lineno)

    if kw == "LOG":
        if not args:
            raise ScriptSyntaxError("LOG requires a message", lineno)
        msg = " ".join(args).strip('"\'')
        return Command("LOG", args=[msg], lineno=lineno)

    if kw == "CALL":
        need(1)
        return Command("CALL", args=[args[0]], lineno=lineno)

    if kw == "DAQ_DIGITAL":
        # Accept both comma-separated and space-separated: "Dev1/port0/line1, 1" or "Dev1/port0/line1 1"
        parts = csv_args() if "," in " ".join(args) else args
        if len(parts) < 2:
            raise ScriptSyntaxError(
                "DAQ_DIGITAL requires a channel and a value (0 or 1).\n"
                "  Examples:  DAQ_DIGITAL Dev1/port0/line1 1\n"
                "             DAQ_DIGITAL Dev1/port0/line1, 1",
                lineno,
            )
        return Command("DAQ_DIGITAL", args=parts[:2], lineno=lineno)

    if kw == "DAQ_ANALOG":
        parts = csv_args() if "," in " ".join(args) else args
        if len(parts) < 5:
            raise ScriptSyntaxError(
                "DAQ_ANALOG requires 5 arguments: channel, waveform, freq, amp, duration.\n"
                "  Example:  DAQ_ANALOG Dev1/ao0, sine, 1.0, 5.0, 2.0\n"
                "            DAQ_ANALOG Dev1/ao0 sine 1.0 5.0 2.0",
                lineno,
            )
        return Command("DAQ_ANALOG", args=parts[:5], lineno=lineno)

    if kw == "DAQ_PULSE":
        parts = csv_args() if "," in " ".join(args) else args
        if len(parts) < 2:
            raise ScriptSyntaxError(
                "DAQ_PULSE requires a channel and a duration in seconds.\n"
                "  Examples:  DAQ_PULSE Dev1/port0/line0 0.1\n"
                "             DAQ_PULSE Dev1/port0/line0, 0.1",
                lineno,
            )
        return Command("DAQ_PULSE", args=parts[:2], lineno=lineno)

    if kw == "TIMELAPSE":
        need(2)
        try:
            int(args[0])
            float(args[1])
        except ValueError:
            raise ScriptSyntaxError(
                "TIMELAPSE <n_frames> <interval_s> [playback_fps]", lineno
            )
        pargs = [args[0], args[1]] + (args[2:3] if len(args) > 2 else [])
        return Command("TIMELAPSE", args=pargs, lineno=lineno)

    raise ScriptSyntaxError(f"Unknown command: {keyword!r}", lineno)


# ── Engine ────────────────────────────────────────────────────────────────────

class ScriptEngine:
    """
    Parses and executes acquisition protocol scripts.
    Call load() once, then run() in a background thread.
    """

    def __init__(self) -> None:
        self._abort = threading.Event()
        self._functions: Dict[str, List[Command]] = {}
        self._top_level: List[Command] = []
        self._ctx: Optional[ScriptContext] = None
        self._start_time: float = 0.0
        self._iter_stack: List[int] = []   # one entry per active REPEAT nesting level

    def load(self, text: str) -> None:
        """Parse script text. Raises ScriptSyntaxError on invalid syntax."""
        self._functions, self._top_level = parse(text)

    def run(self, ctx: ScriptContext) -> None:
        """Execute the loaded script. Blocks the calling thread until done or aborted."""
        self._abort.clear()
        self._iter_stack.clear()
        self._ctx = ctx
        self._start_time = time.monotonic()
        ctx.session_start = datetime.now().isoformat()
        try:
            self._execute_block(self._top_level, ctx)
        finally:
            self._flush_session_log(ctx)

    def abort(self) -> None:
        """Thread-safe stop. Unblocks any active WAITKEY or DELAY."""
        self._abort.set()
        if self._ctx is not None:
            self._ctx.key_event.set()   # wake WAITKEY if blocked

    @staticmethod
    def _ensure_daq(channel: str, ctx: "ScriptContext") -> None:
        """Auto-create a DAQ interface if ctx.daq is None.

        Parses the device name from the channel path (the part before the first '/')
        so scripts work without requiring the user to click Connect in the panel first.
        """
        if ctx.daq is not None:
            return
        device = channel.split("/")[0].strip() if "/" in channel else channel.strip()
        if not device:
            device = "Dev1"
        log = ctx.log_callback
        if log:
            log(f"[DAQ] Auto-connecting to device '{device}'")
        ctx.daq = make_daq(device, log_fn=log)

    @staticmethod
    def _flush_session_log(ctx: "ScriptContext") -> None:
        """Write (or overwrite) acquisition_log.json and acquisition.h5."""
        if not ctx.session_log:
            return
        out_dir = ctx.output_dir or "."
        log_path = os.path.join(out_dir, "acquisition_log.json")
        payload = {
            "script_run": ctx.session_start,
            "output_dir": out_dir,
            "recordings": ctx.session_log,
        }
        try:
            os.makedirs(out_dir, exist_ok=True)
            with open(log_path, "w", encoding="utf-8") as _f:
                json.dump(payload, _f, indent=2)
        except OSError:
            pass  # best-effort; don't surface log-write failures to the user

        # Write acquisition metadata H5 (best-effort; failure must not abort cleanup)
        try:
            import h5py
            h5_path = os.path.join(out_dir, "acquisition.h5")
            with h5py.File(h5_path, "w") as f:
                acq = f.create_group("acquisition")
                acq.attrs["script_run"] = ctx.session_start
                acq.attrs["subject"] = ctx.subject
                acq.attrs["condition"] = ctx.condition
                acq.attrs["replicate"] = ctx.replicate
                cam = acq.create_group("camera")
                cam.attrs["fps"] = ctx.camera_fps
                cam.attrs["exposure"] = ctx.camera_exposure
                cam.attrs["gain"] = ctx.camera_gain
                cam.attrs["width"] = ctx.camera_width
                cam.attrs["height"] = ctx.camera_height
                watch = ctx.camera_worker.watch_rect if ctx.camera_worker else None
                if watch is not None and not watch.isNull():
                    ww = acq.create_group("watch_window")
                    ww.attrs["x"] = watch.x()
                    ww.attrs["y"] = watch.y()
                    ww.attrs["w"] = watch.width()
                    ww.attrs["h"] = watch.height()
        except Exception:
            pass

    def is_aborted(self) -> bool:
        return self._abort.is_set()

    # ── String interpolation ──────────────────────────────────────────────────

    def _interpolate(self, s: str, ctx: ScriptContext) -> str:
        """Substitute {variable} placeholders in string arguments.

        Available variables:
          {iter}      — 1-based iteration index of the innermost REPEAT (0 outside any REPEAT)
          {count}     — current value of the COUNT counter
          {video}     — current video file index (increments after each RECORD)
          {subject}   — SET subject value
          {condition} — SET condition value
          {replicate} — SET replicate value
        """
        if "{" not in s:
            return s
        try:
            return s.format_map({
                "iter":      self._iter_stack[-1] if self._iter_stack else 0,
                "count":     ctx.count,
                "video":     ctx.video_counter,
                "subject":   ctx.subject,
                "condition": ctx.condition,
                "replicate": ctx.replicate,
            })
        except (KeyError, ValueError):
            return s  # unknown placeholder — return as-is rather than crashing

    # ── Block / command dispatch ──────────────────────────────────────────────

    def _execute_block(self, commands: List[Command], ctx: ScriptContext) -> None:
        for cmd in commands:
            if self.is_aborted():
                return
            self._execute_one(cmd, ctx)

    def _execute_one(self, cmd: Command, ctx: ScriptContext) -> None:  # noqa: C901
        k = cmd.kind

        if k == "REPEAT":
            for i in range(1, int(cmd.args[0]) + 1):
                if self.is_aborted():
                    return
                self._iter_stack.append(i)
                try:
                    self._execute_block(cmd.body, ctx)
                finally:
                    self._iter_stack.pop()

        elif k == "CALL":
            body = self._functions.get(cmd.args[0])
            if body is None:
                raise RuntimeError(f"Undefined function: {cmd.args[0]!r}")
            self._execute_block(body, ctx)

        elif k == "SET":
            self._do_set(cmd.args[0], self._interpolate(cmd.args[1], ctx), ctx)

        elif k == "LOAD_ROIS":
            self._do_load_rois(cmd.args[0], ctx)

        elif k == "CAMERA":
            self._do_camera(cmd.args[0], int(cmd.args[1]), ctx)

        elif k == "WATCH":
            if ctx.camera_worker:
                x      = int(cmd.args[0])
                width  = int(cmd.args[1])
                y      = int(cmd.args[2])
                height = int(cmd.args[3])
                ctx.camera_worker.set_watch_window(x, y, width, height)

        elif k == "OUTPUTDIR":
            ctx.output_dir = self._interpolate(cmd.args[0], ctx)
            os.makedirs(ctx.output_dir, exist_ok=True)
            self._do_log(f"Output dir: {ctx.output_dir}", ctx)

        elif k == "ELAPSE":
            elapsed = time.monotonic() - self._start_time
            mins, secs = divmod(int(elapsed), 60)
            self._do_log(f"Elapsed: {mins:02d}:{secs:02d} ({elapsed:.1f} s)", ctx)

        elif k == "COUNT":
            ctx.count += 1
            self._do_log(f"Count: {ctx.count}", ctx)

        elif k == "DELAY":
            self._do_delay(float(cmd.args[0]))

        elif k == "RECORD":
            self._do_record(float(cmd.args[0]), ctx)

        elif k == "SNAPSHOT":
            self._do_snapshot(cmd.args, ctx)

        elif k == "WAITKEY":
            self._do_waitkey(cmd.args[0], ctx)

        elif k == "LOG":
            self._do_log(self._interpolate(cmd.args[0], ctx), ctx)

        elif k == "DAQ_DIGITAL":
            channel = cmd.args[0]
            value   = bool(int(cmd.args[1]))
            self._ensure_daq(channel, ctx)
            try:
                ctx.daq.digital_out(channel, value)
            except Exception as exc:
                msg = (
                    f"DAQ_DIGITAL failed — channel: '{channel}', "
                    f"value: {int(value)}\n"
                    f"  Error: {exc}\n"
                    f"  Check that the device is connected, the channel path is correct\n"
                    f"  (e.g. Dev1/port0/line1), and NI-DAQmx runtime is installed."
                )
                self._do_log(msg, ctx)
                raise RuntimeError(msg) from exc

        elif k == "DAQ_ANALOG":
            channel, waveform, freq, amp, dur = cmd.args[:5]
            self._ensure_daq(channel, ctx)
            try:
                data = generate_waveform(waveform, float(freq), float(amp), float(dur))
                ctx.daq.analog_waveform(channel, data, 10_000.0)
            except Exception as exc:
                msg = (
                    f"DAQ_ANALOG failed — channel: '{channel}', "
                    f"waveform: {waveform}, freq: {freq} Hz, amp: {amp} V, dur: {dur} s\n"
                    f"  Error: {exc}\n"
                    f"  Check that the channel is an analog output (ao) channel\n"
                    f"  and that the voltage range is within the device limits."
                )
                self._do_log(msg, ctx)
                raise RuntimeError(msg) from exc

        elif k == "DAQ_PULSE":
            channel, dur = cmd.args[:2]
            self._ensure_daq(channel, ctx)
            try:
                ctx.daq.digital_out(channel, True)
            except Exception as exc:
                msg = (
                    f"DAQ_PULSE failed to set '{channel}' high\n"
                    f"  Error: {exc}\n"
                    f"  Check that the device is connected and the channel path is correct."
                )
                self._do_log(msg, ctx)
                raise RuntimeError(msg) from exc
            try:
                self._do_delay(float(dur))
            finally:
                try:
                    ctx.daq.digital_out(channel, False)
                except Exception as exc:
                    self._do_log(
                        f"DAQ_PULSE: failed to set '{channel}' low after pulse: {exc}", ctx
                    )

        elif k == "TIMELAPSE":
            n_frames   = int(cmd.args[0])
            interval_s = float(cmd.args[1])
            playback_fps = float(cmd.args[2]) if len(cmd.args) > 2 else 24.0
            self._do_timelapse(n_frames, interval_s, playback_fps, ctx)

    # ── Individual command implementations ────────────────────────────────────

    def _do_delay(self, seconds: float) -> None:
        """Sleep for *seconds* while checking for abort every 50 ms."""
        end = time.monotonic() + seconds
        while time.monotonic() < end and not self.is_aborted():
            time.sleep(min(0.05, end - time.monotonic()))

    def _do_set(self, key: str, value: str, ctx: ScriptContext) -> None:
        kl = key.lower()
        if kl in ("fps", "frame_rate"):
            if ctx.camera_worker:
                ctx.camera_worker.set_parameter("fps", float(value))
        elif kl == "exposure":
            if ctx.camera_worker:
                ctx.camera_worker.set_parameter("exposure", float(value))
        elif kl == "gain":
            if ctx.camera_worker:
                ctx.camera_worker.set_parameter("gain", float(value))
        elif kl == "output":
            ctx.output_dir = value
        elif kl == "subject":
            ctx.subject = value
        elif kl == "condition":
            ctx.condition = value
        elif kl == "replicate":
            try:
                ctx.replicate = int(value)
            except ValueError:
                self._do_log(f"SET replicate: expected integer, got {value!r} — ignored", ctx)
        elif kl == "skip_recording":
            ctx.skip_recording = value.lower() in ("true", "1", "yes")
        elif kl == "watch_window":
            # value is a named ROI file; first ROI defines the watch window extent
            if ctx.app_paths and ctx.camera_worker:
                try:
                    rois = ctx.app_paths.load_rois(value)
                    if rois:
                        r = rois[0]
                        ctx.camera_worker.set_watch_window(
                            int(r.get("x", 0)), int(r.get("y", 0)),
                            int(r.get("w", 640)), int(r.get("h", 480)),
                        )
                        self._do_log(f"Watch window set from ROI file {value!r}", ctx)
                except Exception as exc:
                    self._do_log(f"SET watch_window failed: {exc}", ctx)
        else:
            self._do_log(f"SET: unknown key {key!r} — ignored", ctx)

    def _do_load_rois(self, name: str, ctx: ScriptContext) -> None:
        if ctx.app_paths:
            try:
                rois = ctx.app_paths.load_rois(name)
                ctx.loaded_rois = rois
                self._do_log(f"Loaded ROIs: {name!r} ({len(rois)} regions)", ctx)
            except Exception as exc:
                self._do_log(f"LOAD_ROIS failed ({name!r}): {exc}", ctx)

    def _do_record(self, duration_s: float, ctx: ScriptContext) -> None:
        if ctx.skip_recording:
            self._do_log(f"RECORD: skip_recording=True — skipping {duration_s:.1f} s", ctx)
            self._do_delay(duration_s)
            return

        if not ctx.camera_worker:
            self._do_log("RECORD: no camera open — skipping", ctx)
            return

        out_dir = ctx.output_dir or "."
        os.makedirs(out_dir, exist_ok=True)

        parts = [p for p in (ctx.subject, ctx.condition) if p]
        if parts:
            prefix = "_".join(parts) + f"_{ctx.replicate:02d}_"
        else:
            prefix = "video_"
        fname = f"{prefix}{ctx.video_counter:04d}.mp4"
        out_path = os.path.join(out_dir, fname)

        if os.path.exists(out_path):
            raise RuntimeError(
                f"RECORD aborted — file already exists: '{fname}'\n"
                f"  Increment SET replicate, change the output directory, or delete the file first."
            )

        fps = getattr(ctx.camera_worker, "software_fps", 25.0)
        ctx.camera_worker.start_recording(out_path, fps)
        self._do_log(f"Recording {fname} ({duration_s:.1f} s @ {fps:.1f} fps)…", ctx)
        record_start = time.monotonic()
        try:
            self._do_delay(duration_s)
        finally:
            # Always stop recording — even if aborted or an exception fires mid-delay.
            ctx.camera_worker.stop_recording()

        actual_duration = time.monotonic() - record_start
        aborted = self.is_aborted()

        # Use the actual path chosen by the camera worker (codec may have changed extension).
        actual_path = getattr(ctx.camera_worker, "last_recording_path", None) or out_path
        actual_fname = os.path.basename(actual_path)

        if aborted:
            self._do_log(f"Recording stopped early ({actual_duration:.1f} s): {actual_fname}", ctx)
        else:
            ctx.video_counter += 1
            self._do_log(f"Saved {actual_fname}", ctx)

        writer_fps = getattr(ctx.camera_worker, "last_writer_fps", fps)
        frames_written = getattr(ctx.camera_worker, "last_record_frame_count", 0)
        if frames_written > 0 and actual_duration > 0:
            actual_fps = frames_written / actual_duration
        else:
            actual_fps = writer_fps

        # Warn if the camera delivered significantly fewer frames than requested;
        # this causes the output video to be shorter than the requested duration.
        if actual_duration > 0 and abs(actual_fps - fps) > 1.0:
            expected_frames = int(fps * actual_duration)
            video_duration = frames_written / writer_fps if writer_fps > 0 else 0.0
            self._do_log(
                f"WARNING: camera delivered {actual_fps:.1f} fps (target {fps:.1f} fps) — "
                f"{frames_written}/{expected_frames} frames written; "
                f"video is {video_duration:.1f}s, not {actual_duration:.1f}s", ctx
            )

        meta = {
            "filename": actual_fname,
            "subject": ctx.subject,
            "condition": ctx.condition,
            "replicate": ctx.replicate,
            "duration_s": round(actual_duration, 2),
            "requested_duration_s": duration_s,
            "target_fps": fps,
            "actual_fps": round(actual_fps, 2),
            "writer_fps": round(writer_fps, 2),
            "frames_written": frames_written,
            "timestamp": datetime.now().isoformat(),
            "output_dir": out_dir,
        }
        if aborted:
            meta["aborted"] = True
        ctx.session_log.append(meta)
        self._flush_session_log(ctx)

    def _do_snapshot(self, args: List[str], ctx: ScriptContext) -> None:
        if not ctx.camera_worker:
            self._do_log("SNAPSHOT: no camera available — skipping", ctx)
            return

        out_dir = ctx.output_dir or "."
        os.makedirs(out_dir, exist_ok=True)

        if not args:
            ctx.camera_worker.snap_image()
            self._do_log("Snapshot taken", ctx)
            return

        first = args[0].lower()

        if first == "ref":
            ctx.camera_worker.snap_image()
            self._do_log("Preview reference updated", ctx)

        elif first == "bg":
            frames = int(args[1]) if len(args) > 1 else 10
            blur_k = int(args[2]) if len(args) > 2 else 5
            bg_path = os.path.join(out_dir, "background.png")
            done = ctx.snap_event
            done.clear()
            ctx.camera_worker.capture_background(frames, blur_k, bg_path, done)
            self._do_log(f"Capturing background ({frames} frames, blur={blur_k})…", ctx)
            done.wait(timeout=max(30.0, frames * 2.0))
            self._do_log("Background capture complete", ctx)

        else:
            prefix = self._interpolate(args[0], ctx)
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            fname = f"{prefix}_{ts}.png"
            path = os.path.join(out_dir, fname)
            done = ctx.snap_event
            done.clear()
            ctx.camera_worker.snap_to_file(path, done)
            done.wait(timeout=5.0)
            self._do_log(f"Snapshot: {fname}", ctx)

    def _do_camera(self, backend: str, index: int, ctx: ScriptContext) -> None:
        if not ctx.camera_worker:
            self._do_log("CAMERA: no camera proxy available", ctx)
            return
        ctx.camera_worker.close_camera()
        self._do_delay(0.3)
        ctx.camera_worker.open_camera(backend, index)
        self._do_delay(2.0)  # allow hardware to initialize
        self._do_log(f"Camera: {backend}[{index}] ready", ctx)

    def _do_waitkey(self, expected_key: str, ctx: ScriptContext) -> None:
        self._do_log(f"Waiting for key: {expected_key!r}…", ctx)
        if ctx.waitkey_callback is not None:
            ctx.waitkey_callback()
        while not self.is_aborted():
            ctx.key_event.clear()
            # Block until a key arrives or abort fires (timeout so abort is checked)
            ctx.key_event.wait(timeout=0.1)
            if self.is_aborted():
                return
            if ctx.key_event.is_set():
                pressed = ctx.last_key.lower()
                if self._key_matches(pressed, expected_key):
                    return
                # Wrong key — keep waiting

    @staticmethod
    def _key_matches(pressed: str, expected: str) -> bool:
        _ALIASES = {
            "space": " ", "enter": "\r", "return": "\r",
            "escape": "\x1b", "esc": "\x1b",
        }
        if expected == "any" or expected == "":
            return True
        norm_p = _ALIASES.get(pressed, pressed)
        norm_e = _ALIASES.get(expected, expected)
        return norm_p == norm_e

    def _do_timelapse(
        self,
        n_frames: int,
        interval_s: float,
        playback_fps: float,
        ctx: ScriptContext,
    ) -> None:
        if not ctx.camera_worker:
            self._do_log("TIMELAPSE: no camera open — skipping", ctx)
            return

        out_dir = ctx.output_dir or "."
        os.makedirs(out_dir, exist_ok=True)

        parts = [p for p in (ctx.subject, ctx.condition) if p]
        prefix = "_".join(parts) + f"_{ctx.replicate:02d}_" if parts else "timelapse_"
        fname = f"{prefix}{ctx.video_counter:04d}.mp4"
        out_path = os.path.join(out_dir, fname)

        # Grab first frame to establish frame dimensions.
        frame0 = ctx.camera_worker.grab_frame()
        if frame0 is None:
            self._do_log("TIMELAPSE: could not read first frame from camera", ctx)
            return
        if frame0.ndim == 2:
            frame0 = cv2.cvtColor(frame0, cv2.COLOR_GRAY2BGR)
        h, w = frame0.shape[:2]

        # Open VideoWriter — try codecs in preference order.
        writer = None
        chosen_path = out_path
        base, _ = os.path.splitext(out_path)
        for fourcc_str, ext in (("mp4v", ".mp4"), ("avc1", ".mp4"), ("XVID", ".avi"), ("MJPG", ".avi")):
            candidate = base + ext
            fourcc = cv2.VideoWriter_fourcc(*fourcc_str)
            w_try = cv2.VideoWriter(candidate, fourcc, playback_fps, (w, h))
            if w_try.isOpened():
                chosen_path = candidate
                writer = w_try
                break
            w_try.release()

        if writer is None:
            self._do_log(f"TIMELAPSE: could not open VideoWriter for {out_path}", ctx)
            return

        actual_fname = os.path.basename(chosen_path)
        total_real_s = interval_s * (n_frames - 1)
        self._do_log(
            f"TIMELAPSE: {actual_fname} — {n_frames} frames, "
            f"every {interval_s:.0f} s, "
            f"total real time {total_real_s / 60:.1f} min, "
            f"playback {playback_fps:.0f} fps",
            ctx,
        )

        written = 0
        start_time = datetime.now().isoformat()
        try:
            # Write first frame (already grabbed above).
            writer.write(frame0)
            written = 1
            self._do_log(f"TIMELAPSE: frame 1/{n_frames}", ctx)

            for i in range(1, n_frames):
                if self.is_aborted():
                    break
                self._do_delay(interval_s)
                if self.is_aborted():
                    break
                frame = ctx.camera_worker.grab_frame()
                if frame is not None:
                    if frame.ndim == 2:
                        frame = cv2.cvtColor(frame, cv2.COLOR_GRAY2BGR)
                    fh, fw = frame.shape[:2]
                    if (fh, fw) != (h, w):
                        frame = cv2.resize(frame, (w, h))
                    writer.write(frame)
                    written += 1
                    self._do_log(f"TIMELAPSE: frame {written}/{n_frames}", ctx)
                else:
                    self._do_log(f"TIMELAPSE: frame {i + 1} skipped — no frame from camera", ctx)
        finally:
            writer.release()

        ctx.video_counter += 1
        self._do_log(f"TIMELAPSE: saved {actual_fname} ({written} frames)", ctx)

        meta = {
            "filename": actual_fname,
            "subject": ctx.subject,
            "condition": ctx.condition,
            "replicate": ctx.replicate,
            "frames_captured": written,
            "frames_requested": n_frames,
            "interval_s": interval_s,
            "playback_fps": playback_fps,
            "timestamp": start_time,
            "output_dir": out_dir,
        }
        if written < n_frames:
            meta["aborted"] = True
        meta_path = os.path.splitext(chosen_path)[0] + ".json"
        try:
            with open(meta_path, "w", encoding="utf-8") as _f:
                json.dump(meta, _f, indent=2)
        except OSError as _e:
            self._do_log(f"Warning: could not write timelapse metadata: {_e}", ctx)

    def _do_log(self, msg: str, ctx: ScriptContext) -> None:
        ts = datetime.now().strftime("%H:%M:%S")
        full = f"[{ts}] {msg}"
        if ctx.log_callback:
            ctx.log_callback(full)
        else:
            print(full)
