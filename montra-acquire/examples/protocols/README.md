# Acquisition Protocol Examples

`.acq` files are plain-text scripts executed by the acquisition software's built-in
script engine.  Load them via **File → Open Script** in the Acquisition window, then
click **Run**.

---

## Scripting API

### Camera and output

| Command | Syntax | Description |
|---------|--------|-------------|
| `SET` | `SET fps = 25` | Set a camera parameter or session variable (`fps`, `exposure`, `gain`, `subject`, `condition`, `replicate`, `skip_recording`) |
| `CAMERA` | `CAMERA IDS 0` | Open a camera by backend (`IDS`, `FLIR`, `OpenCV`, `Test`) and index |
| `WATCH` | `WATCH x width y height` | Set the camera watch window (pixels) |
| `OUTPUTDIR` | `OUTPUTDIR D:\Data\{subject}` | Change the output directory; supports `{variable}` substitution |
| `SNAPSHOT` | `SNAPSHOT` | Grab a frame without saving |
| `SNAPSHOT` | `SNAPSHOT prefix` | Save a PNG as `prefix_YYYYMMDD_HHMMSS.png` |
| `SNAPSHOT` | `SNAPSHOT bg 30 5` | Build a background image from N frames with blur kernel K |
| `LOAD_ROIS` | `LOAD_ROIS name` | Load a saved ROI file by name for use by SNAPSHOT bg |

### Recording

| Command | Syntax | Description |
|---------|--------|-------------|
| `RECORD` | `RECORD 60` | Record video for N seconds and save to the output directory |
| `TIMELAPSE` | `TIMELAPSE 120 30.0 24` | Capture 1 frame every 30 s (120 frames total), write as 24 fps video |

### Flow control

| Command | Syntax | Description |
|---------|--------|-------------|
| `DELAY` | `DELAY 3` | Pause for N seconds |
| `WAITKEY` | `WAITKEY space` | Block until a key is pressed (`space`, `enter`, `escape`, or any char) |
| `REPEAT` | `REPEAT 5:` … `END` | Repeat a block N times; `{iter}` gives the 1-based iteration index |
| `DEF` / `CALL` | `DEF name:` … `END` then `CALL name` | Define and call reusable blocks |

### Logging and counters

| Command | Syntax | Description |
|---------|--------|-------------|
| `LOG` | `LOG "message"` | Write a timestamped message to the console and acquisition log |
| `ELAPSE` | `ELAPSE` | Log elapsed time since script start |
| `COUNT` | `COUNT` | Increment an internal counter and log its value; `{count}` in strings |

### DAQ

| Command | Syntax | Description |
|---------|--------|-------------|
| `DAQ_DIGITAL` | `DAQ_DIGITAL Dev1/port0/line0, 1` | Set a digital output channel high (1) or low (0) |
| `DAQ_PULSE` | `DAQ_PULSE Dev1/port0/line0, 0.5` | Set a channel high, wait N seconds, then set it low |
| `DAQ_ANALOG` | `DAQ_ANALOG Dev1/ao0, sine, 1.0, 5.0, 2.0` | Output a waveform (`sine`, `square`, `ramp`) at freq Hz, amp V, for duration s |

---

### String interpolation

`OUTPUTDIR`, `LOG`, and `SNAPSHOT prefix` arguments support `{variable}` substitution:

| Variable | Value |
|----------|-------|
| `{iter}` | 1-based iteration index of the current `REPEAT` (0 outside any loop) |
| `{count}` | Current `COUNT` counter value |
| `{video}` | Number of videos recorded so far |
| `{subject}` | `SET subject` value |
| `{condition}` | `SET condition` value |
| `{replicate}` | `SET replicate` value |

Comments begin with `#`.

---

## Protocol Files

| File | Description |
|------|-------------|
| `zebrafish_single_tracking.acq` | Single zebrafish larva — baseline and stimulus recording with DAQ trigger |

---

## Example: multi-condition experiment

```
SET subject    = fish01
SET replicate  = 1

REPEAT 3:
    OUTPUTDIR D:\Data\{subject}_rep{replicate}_trial{iter}

    SET condition = baseline
    LOG "Baseline ({iter}/3)…"
    RECORD 60

    DAQ_PULSE Dev1/port0/line0, 1.0   # 1 s TTL stimulus

    SET condition = post_stimulus
    LOG "Post-stimulus ({iter}/3)…"
    RECORD 120

    DELAY 30
END
```
