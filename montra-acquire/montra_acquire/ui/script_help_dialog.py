"""Non-modal dialog showing the full .acq scripting language reference."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

_HELP_HTML = """
<style>
  body   { font-family: sans-serif; font-size: 13px; margin: 12px; }
  h1     { font-size: 16px; margin-bottom: 4px; }
  h2     { font-size: 14px; color: #336; margin-top: 16px; margin-bottom: 4px; }
  code   { font-family: 'Courier New', monospace; background: #eef; padding: 1px 4px;
           border-radius: 3px; font-size: 12px; }
  pre    { font-family: 'Courier New', monospace; background: #f4f4f4; padding: 10px;
           border-left: 3px solid #88a; margin: 6px 0; font-size: 12px;
           white-space: pre; }
  table  { border-collapse: collapse; width: 100%; margin-top: 6px; }
  th     { background: #dde; text-align: left; padding: 4px 8px; font-size: 12px; }
  td     { padding: 3px 8px; vertical-align: top; border-bottom: 1px solid #ddd; font-size: 12px; }
  .note  { color: #888; font-style: italic; }
</style>

<h1>Acquisition Script Language (.acq)</h1>
<p>One command per line. Comments start with <code>#</code> and run to end-of-line.
Lines are case-insensitive. Indentation is ignored.</p>

<h2>Camera Setup</h2>
<table>
<tr><th>Command</th><th>Description</th></tr>
<tr><td><code>CAMERA &lt;backend&gt; [index]</code></td>
    <td>Open a camera. <code>backend</code>: <code>Test</code>, <code>OpenCV</code>,
        <code>IDS</code>, or <code>FLIR</code>. Optional <code>index</code> selects which device
        (default <code>0</code>). The command waits ~2 s for hardware
        initialisation.</td></tr>
<tr><td><code>SET fps = &lt;number&gt;</code></td>
    <td>Set camera frame rate (also accepts <code>frame_rate</code>).</td></tr>
<tr><td><code>SET exposure = &lt;number&gt;</code></td>
    <td>Set camera exposure time in microseconds.</td></tr>
<tr><td><code>SET gain = &lt;number&gt;</code></td>
    <td>Set camera gain.</td></tr>
<tr><td><code>WATCH &lt;x&gt; &lt;width&gt; &lt;y&gt; &lt;height&gt;</code></td>
    <td>Set the hardware watch window to a pixel rectangle.
        All four arguments are integers (pixels).</td></tr>
<tr><td><code>SET watch_window = &lt;roi_name&gt;</code></td>
    <td>Load a named ROI file and apply the first ROI as the watch window.
        Convenience alternative to <code>WATCH</code> when ROIs are already saved.</td></tr>
</table>

<h2>Recording</h2>
<table>
<tr><th>Command</th><th>Description</th></tr>
<tr><td><code>OUTPUTDIR &lt;path&gt;</code></td>
    <td>Set the output directory for all saved files (creates it if needed).
        Equivalent to <code>SET output = &lt;path&gt;</code>.</td></tr>
<tr><td><code>SET output = &lt;path&gt;</code></td>
    <td>Alias for <code>OUTPUTDIR</code>.</td></tr>
<tr><td><code>RECORD &lt;seconds&gt;</code></td>
    <td>Record video for the specified duration. When <code>subject</code> and/or
        <code>condition</code> are set, files are named
        <code>{subject}_{condition}_{replicate:02d}_0000.mp4</code>;
        otherwise <code>video_0000.mp4</code>, <code>video_0001.mp4</code>, …
        If <code>skip_recording = true</code> the command waits the given duration
        without writing any video (useful when tracking live without saving).</td></tr>
<tr><td><code>SNAPSHOT</code></td>
    <td>Grab a frame and update the preview — no file written.</td></tr>
<tr><td><code>SNAPSHOT &lt;prefix&gt;</code></td>
    <td>Save a PNG image as <code>&lt;prefix&gt;_YYYYMMDD_HHMMSS.png</code>
        in the output directory.</td></tr>
<tr><td><code>SNAPSHOT ref</code></td>
    <td>Update the preview reference frame (used as a visual baseline).</td></tr>
<tr><td><code>SNAPSHOT bg [frames] [blur]</code></td>
    <td>Build a background image by averaging <code>frames</code> frames
        (default 10) with Gaussian blur radius <code>blur</code> (default 5).
        Saved as <code>background.png</code> in the output directory.</td></tr>
<tr><td><code>TIMELAPSE &lt;n_frames&gt; &lt;interval_s&gt; [playback_fps]</code></td>
    <td>Capture one frame every <code>interval_s</code> seconds for a total of
        <code>n_frames</code> frames and assemble them into a single MP4.
        <code>playback_fps</code> controls playback speed of the output video
        (default <code>24</code>). Files follow the same naming convention as
        <code>RECORD</code>.
        <br><em>Example:</em> <code>TIMELAPSE 60 60.0</code> captures 1 frame/min
        for 1 hour and produces a 2.5-second video at 24 fps.</td></tr>
</table>

<h2>Experiment Metadata</h2>
<p>These keys drive output filenames and are written into every H5 tracking file
as attributes. All are optional — omit any you do not need.</p>
<table>
<tr><th>Command</th><th>Description</th></tr>
<tr><td><code>SET subject = &lt;value&gt;</code></td>
    <td>Biological subject identifier (e.g. <code>Fish1</code>, <code>Worm3</code>).
        Used as the first component of output filenames.</td></tr>
<tr><td><code>SET condition = &lt;value&gt;</code></td>
    <td>Experimental condition label (e.g. <code>control</code>, <code>drug_10uM</code>).
        Used as the second component of output filenames.</td></tr>
<tr><td><code>SET replicate = &lt;integer&gt;</code></td>
    <td>Replicate number within the subject/condition group (default <code>1</code>).
        Zero-padded to two digits in filenames.</td></tr>
<tr><td><code>SET skip_recording = true|false</code></td>
    <td>When <code>true</code>, <code>RECORD</code> waits the specified duration
        but does not write video to disk. Default <code>false</code>.</td></tr>
</table>

<h2>Flow Control</h2>
<table>
<tr><th>Command</th><th>Description</th></tr>
<tr><td><code>DELAY &lt;seconds&gt;</code></td>
    <td>Pause execution for the given duration (float, e.g. <code>0.5</code>).
        Abort-safe: checks Stop every 50 ms.</td></tr>
<tr><td><code>WAITKEY &lt;key&gt;</code></td>
    <td>Block until the specified key is pressed in the acquisition window.
        Key names: <code>space</code>, <code>enter</code>, <code>escape</code>,
        <code>any</code>, or any single character.</td></tr>
<tr><td><code>REPEAT &lt;n&gt;:</code><br>&nbsp;&nbsp;<em>commands</em><br><code>END</code></td>
    <td>Execute the enclosed block exactly <em>n</em> times. Blocks may be nested.</td></tr>
<tr><td><code>DEF &lt;name&gt;:</code><br>&nbsp;&nbsp;<em>commands</em><br><code>END</code></td>
    <td>Define a reusable named sub-routine. Definitions are hoisted — they
        can appear anywhere in the file.</td></tr>
<tr><td><code>CALL &lt;name&gt;</code></td>
    <td>Execute a previously defined sub-routine.</td></tr>
<tr><td><code>LOG "message"</code></td>
    <td>Print a message to the script log and console dock.</td></tr>
<tr><td><code>ELAPSE</code></td>
    <td>Log elapsed time since the script started (mm:ss format).</td></tr>
<tr><td><code>COUNT</code></td>
    <td>Increment an internal counter (starting from 0) and log the new value.
        Useful for tracking loop iterations or trial numbers.</td></tr>
</table>

<h2>ROIs</h2>
<table>
<tr><th>Command</th><th>Description</th></tr>
<tr><td><code>LOAD_ROIS &lt;name&gt;</code></td>
    <td>Load a saved ROI set into the script context. The name matches a file
        in <code>rois/</code> (without the <code>.json</code> extension).</td></tr>
</table>

<h2>DAQ Output</h2>
<table>
<tr><th>Command</th><th>Description</th></tr>
<tr><td><code>DAQ_DIGITAL &lt;channel&gt; &lt;0|1&gt;</code></td>
    <td>Set a digital output line high (<code>1</code>) or low (<code>0</code>).
        Channel and value may be separated by a space or a comma.<br>
        <em>e.g.</em> <code>DAQ_DIGITAL Dev1/port0/line1 1</code></td></tr>
<tr><td><code>DAQ_ANALOG &lt;channel&gt; &lt;waveform&gt; &lt;freq&gt; &lt;amp&gt; &lt;duration&gt;</code></td>
    <td>Output a finite analog waveform. <code>waveform</code>: <code>sine</code>,
        <code>square</code>, <code>ramp</code> (sawtooth).
        <code>freq</code> in Hz, <code>amp</code> in volts,
        <code>duration</code> in seconds. Arguments may be space- or comma-separated.
        Blocks until the waveform completes.</td></tr>
<tr><td><code>DAQ_PULSE &lt;channel&gt; &lt;duration_s&gt;</code></td>
    <td>Send a digital high pulse of the given duration in seconds, then return
        the line low. Space or comma separator accepted. Abort-safe.</td></tr>
</table>

<h2>Live Tracking</h2>
<table>
<tr><th>Command</th><th>Description</th></tr>
<tr><td><code>TRACK &lt;config_name&gt;</code></td>
    <td>Start real-time tracking using a named config from
        <code>configs/tracking/</code> (without <code>.json</code>).
        The preview switches to annotated tracking output.</td></tr>
<tr><td><code>TRACK_OFF</code></td>
    <td>Stop real-time tracking and return the preview to raw camera frames.</td></tr>
</table>

<h2>Example — Stimulation + recording</h2>
<pre>
SET fps      = 25
SET exposure = 8000
DELAY 5                            # camera warm-up

LOG "Baseline"
RECORD 60

DAQ_PULSE Dev1/port0/line0, 0.1    # brief stimulus pulse

LOG "Post-stimulus"
RECORD 120

LOG "Done"
</pre>

<h2>Example — Time-lapse (1 frame/min, 1 hour)</h2>
<pre>
SET subject   = Worm1
SET condition = control
SET output    = D:/data/timelapse

# 60 frames × 60 s interval = 1 hour real time
# Output plays back at 24 fps → 2.5-second video
TIMELAPSE 60 60.0 24

LOG "Timelapse complete"
</pre>

<h2>Example — Looped multi-condition</h2>
<pre>
DEF capture_condition:
    RECORD 30
    DELAY 5
END

REPEAT 3:
    CALL capture_condition
    DAQ_DIGITAL Dev1/port0/line0, 1
    DELAY 2
    DAQ_DIGITAL Dev1/port0/line0, 0
    DELAY 10
END
</pre>

<h2>Example — Live zebrafish tracking</h2>
<pre>
TRACK zebrafish_single

LOG "Press SPACE to begin recording"
WAITKEY space

RECORD 300      # 5 minutes with tracking active

TRACK_OFF
LOG "Done"
</pre>

<h2>Example — Multi-subject experiment with metadata</h2>
<pre>
SET fps    = 25
OUTPUTDIR D:/data/experiment_01

# --- Subject 1 ---
SET subject   = Fish1
SET condition = control
SET replicate = 1

TRACK zebrafish_single
LOG "Fish1 control — press SPACE to record"
WAITKEY space
RECORD 300          # saves Fish1_control_01_0000.mp4
TRACK_OFF
DELAY 30            # recovery period

# --- Subject 2, treatment condition ---
SET subject   = Fish2
SET condition = drug_10uM
SET replicate = 1

TRACK zebrafish_single
LOG "Fish2 drug — press SPACE to record"
WAITKEY space
RECORD 300          # saves Fish2_drug_10uM_01_0000.mp4
TRACK_OFF

LOG "Experiment complete"
</pre>

<h2>Example — Live-only tracking (no video saved)</h2>
<pre>
SET subject        = Fish3
SET condition      = control
SET skip_recording = true   # track live but don't write video

TRACK zebrafish_single
LOG "Live tracking active — press SPACE when done"
WAITKEY space
RECORD 300          # waits 300 s, no file written
TRACK_OFF
</pre>

<h2>Example — Background capture then record</h2>
<pre>
SET fps    = 25
OUTPUTDIR  D:/data/run01

# Build background from 30 frames (saved as background.png)
SNAPSHOT bg 30 5

LOG "Press SPACE to start recording"
WAITKEY space

TRACK my_tracking_config
RECORD 120
TRACK_OFF
</pre>
"""


class ScriptHelpDialog(QDialog):
    """Non-modal dialog with the full .acq scripting language reference."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent, Qt.WindowType.Window)
        self.setWindowTitle("Script Language Reference")
        self.resize(700, 620)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        browser = QTextBrowser()
        browser.setOpenExternalLinks(False)
        browser.setHtml(_HELP_HTML)
        layout.addWidget(browser)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.close)
        layout.addWidget(buttons)
