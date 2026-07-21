"""Script execution worker.

One-shot QObject that runs a single ScriptEngine.run() call in a background
QThread.  Constructed once and reused across script runs; abort() is safe to
call from any thread.

Thread model:
  The worker lives in a dedicated QThread.  run() is invoked via a queued
  signal from the acquisition thread; it blocks the worker thread until the
  script finishes, is aborted, or raises.

Signals emitted:
  progress(str)  — timestamped log messages from the script engine
  finished()     — script completed normally
  aborted()      — script was stopped via abort()
  error(str)     — unhandled exception in the script engine
"""
from __future__ import annotations

from PySide6.QtCore import QObject, Signal, Slot

from montra_acquire.script_engine import ScriptContext, ScriptEngine, ScriptSyntaxError


class AcquisitionWorker(QObject):
    """Runs a ScriptEngine in a background QThread.

    Move this object to a QThread, then invoke run() via a queued signal.
    abort() is safe to call directly from any thread.
    """

    progress = Signal(str)   # timestamped log messages from the script
    finished = Signal()
    error    = Signal(str)
    aborted  = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._engine  = ScriptEngine()
        self._running = False

    @Slot(str, object)
    def run(self, script_text: str, ctx: ScriptContext) -> None:
        """Parse and execute *script_text*. Blocks the calling thread until done."""
        if self._running:
            return
        self._running = True

        try:
            self._engine.load(script_text)
        except ScriptSyntaxError as exc:
            self.error.emit(str(exc))
            self._running = False
            return

        ctx.log_callback = self.progress.emit

        try:
            self._engine.run(ctx)
            if self._engine.is_aborted():
                self.aborted.emit()
            else:
                self.finished.emit()
        except BaseException as exc:
            # BaseException catches KeyboardInterrupt / SystemExit that Exception misses;
            # emit as an error so the UI recovers cleanly rather than crashing.
            try:
                self.error.emit(f"Script runtime error: {exc}")
            except Exception:
                pass
            if isinstance(exc, (SystemExit, KeyboardInterrupt)):
                raise
        finally:
            self._running = False

    def abort(self) -> None:
        """Thread-safe stop. Safe to call from any thread."""
        self._engine.abort()
