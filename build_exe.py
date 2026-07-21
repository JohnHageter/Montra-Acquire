"""
Output (default --onedir):
    dist/
      Montra-Acquire/
        Montra-Acquire.exe   ← double-click to run
        _internal/           ← DLLs / Python files (must stay next to the exe)

    dist/
      Montra-Acquire.zip     ← copy this zip to the target PC and unzip

Usage:
    python build_exe.py                  # build the acquire app
    python build_exe.py --onefile        # single exe (slower startup, ~30 s for PySide6)
    python build_exe.py --no-zip         # skip zip creation
    python build_exe.py --clean          # delete dist/ and build/ first

Notes:
    - Camera drivers (IDS GeniCam transport layers) must be separately installed
      on the target PC using the IDS peak runtime installer.
    - The target PC needs the Visual C++ Redistributable (vc_redist.x64.exe)
      if not already present.  It is almost always pre-installed on Windows 10/11.
"""
from __future__ import annotations

import argparse
import os
import shutil
import stat
import subprocess
import sys
import zipfile
from pathlib import Path

REPO = Path(__file__).resolve().parent
DIST = REPO / "dist"
BUILD = REPO / "build"

_HIDDEN = [
    "h5py._hl",
    "h5py._hl.files",
    "h5py._hl.group",
    "h5py._hl.dataset",
    "cv2",
    "PySide6.QtCore",
    "PySide6.QtGui",
    "PySide6.QtWidgets",
    "PySide6.QtOpenGL",
    "PySide6.QtOpenGLWidgets",
    "montra.tracker.roi",
    "montra.io",
    "montra.io.Camera",
    "montra.io.OpenCVCamera",
    "montra.io.IDSCamera",
    "montra.io.FLIRCamera",
    "montra.io.TestCamera",
    "ids_peak",
    "ids_peak_ipl",
    "nidaqmx",
    "nidaqmx.task",
    "nidaqmx.constants",
    "nidaqmx.system",
]

_COLLECT_ALL = [
    "montra",
    "montra_acquire",
    "ids_peak",          # bundles GeniCam DLLs from the Python package
    "cv2",
    "PySide6",           # Qt plugins, translations, platform DLLs
    "numpy",             # numpy._core compiled extensions
    "nidaqmx",           # pure-Python but has JSON/grpc data files inside the package
    "nitypes",           # NI types library; required by nidaqmx 1.x at import time
    "decouple",          # python-decouple; imported by nidaqmx._lib at import time
]

_COPY_METADATA = [
    "nidaqmx",
    "nitypes",
]

APP = {
    "entry":  REPO / "montra-acquire" / "main_acquisition.py",
    "name":   "Montra-Acquire",
    "paths":  [REPO / "montra-acquire", REPO / "montra-lib"],
}


def _force_remove(path: Path) -> None:
    """Remove a directory tree, clearing read-only flags on any locked files."""
    def _on_error(func, fpath, _exc):
        os.chmod(fpath, stat.S_IWRITE)
        func(fpath)
    if path.exists():
        shutil.rmtree(path, onerror=_on_error)


def _ensure_pyinstaller() -> None:
    try:
        import PyInstaller  # noqa: F401
    except ImportError:
        print("PyInstaller not found — installing...")
        subprocess.check_call(
            [sys.executable, "-m", "pip", "install",
             "pyinstaller", "pyinstaller-hooks-contrib"],
            stdout=subprocess.DEVNULL,
        )
        print("PyInstaller installed.\n")


def _find_vc_runtime_dlls() -> list[tuple[str, str]]:
    """Find Visual C++ runtime DLLs that python3xx.dll depends on.

    PyInstaller does not always pick these up from conda environments.
    Returns a list of (src_path, dest_dir) tuples for --add-binary.
    """
    py_dir = Path(sys.executable).parent
    search_dirs = [
        py_dir,                          # conda env root
        py_dir / "Library" / "bin",      # conda Library/bin
        py_dir / "DLLs",                 # standard CPython DLLs dir
        Path(r"C:\Windows\System32"),    # system fallback
    ]
    want = [
        "vcruntime140.dll",
        "vcruntime140_1.dll",
        "vcruntime140_threads.dll",
        "msvcp140.dll",
        "msvcp140_1.dll",
        "msvcp140_2.dll",
        "msvcp140_atomic_wait.dll",
        "msvcp140_codecvt_ids.dll",
        "concrt140.dll",
        "ucrtbase.dll",
        "python3.dll",
    ]
    found: list[tuple[str, str]] = []
    for name in want:
        for d in search_dirs:
            candidate = d / name
            if candidate.exists():
                found.append((str(candidate), "."))
                break
    return found


def _add_cv2_config_files(cmd: list) -> None:
    """Explicitly bundle cv2 bootstrap config .py files.

    PyInstaller's collect_data_files() skips .py files, so config.py,
    config-3.py, load_config_py2.py and load_config_py3.py may not reach
    _internal/cv2/ even when --collect-all cv2 is specified.
    """
    import importlib.util
    spec = importlib.util.find_spec("cv2")
    if not spec or not spec.submodule_search_locations:
        print("  WARNING: cv2 package not found — skipping config file bundling")
        return
    cv2_dir = Path(next(iter(spec.submodule_search_locations)))
    config_files = list(cv2_dir.glob("config*.py")) + list(cv2_dir.glob("load_config_py*.py"))
    if config_files:
        print(f"  Explicitly adding {len(config_files)} cv2 config file(s): {[f.name for f in config_files]}")
        for f in config_files:
            cmd += ["--add-data", f"{f}{os.pathsep}cv2"]
    else:
        print("  WARNING: no cv2 config*.py files found — cv2 may fail to load on target PC")


def _build(onefile: bool) -> Path:
    mode = "--onefile" if onefile else "--onedir"
    out_dir = DIST / APP["name"]

    _force_remove(out_dir)

    cmd = [
        sys.executable, "-m", "PyInstaller",
        str(APP["entry"]),
        "--name", APP["name"],
        mode,
        "--windowed",
        "--distpath", str(DIST),
        "--workpath", str(BUILD),
        "--specpath", str(BUILD),
        "--noconfirm",
    ]

    for p in APP["paths"]:
        cmd += ["--paths", str(p)]

    for pkg in _COLLECT_ALL:
        cmd += ["--collect-all", pkg]

    for mod in [
        "PySide6.QtWebEngine",
        "PySide6.QtWebEngineCore",
        "PySide6.QtWebEngineWidgets",
        "PySide6.QtWebEngineQuick",
        "PySide6.QtPdf",
        "PySide6.QtPdfWidgets",
        "torch",
        "torchvision",
        "torchaudio",
        "polars",
        "matplotlib",
        "mypy",
        "IPython",
        "jupyter",
        "ultralytics",
        "scipy",
        "skimage",
    ]:
        cmd += ["--exclude-module", mod]

    for hi in _HIDDEN:
        cmd += ["--hidden-import", hi]

    for pkg in _COPY_METADATA:
        cmd += ["--copy-metadata", pkg]

    _add_cv2_config_files(cmd)

    vc_dlls = _find_vc_runtime_dlls()
    if vc_dlls:
        print(f"  Bundling {len(vc_dlls)} VC runtime DLL(s): {[Path(s).name for s,_ in vc_dlls]}")
    else:
        print("  WARNING: vcruntime140.dll not found — target PC may need VC++ redistributable")
    for src, dest in vc_dlls:
        cmd += ["--add-binary", f"{src}{os.pathsep}{dest}"]

    print(f"\n{'='*60}")
    print(f"Building {APP['name']} ({mode}) ...")
    print(f"{'='*60}")
    subprocess.check_call(cmd)

    if onefile:
        return DIST / (APP["name"] + ".exe")
    return out_dir


def _zip(src: Path, zip_path: Path) -> None:
    print(f"Creating {zip_path.name} ...")
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        if src.is_file():
            zf.write(src, src.name)
        else:
            for f in src.rglob("*"):
                if f.is_file():
                    zf.write(f, f.relative_to(src.parent))
    size_mb = zip_path.stat().st_size / 1_048_576
    print(f"  → {zip_path}  ({size_mb:.0f} MB)")


def main() -> None:
    ap = argparse.ArgumentParser(description="Build Montra-Acquire executable")
    ap.add_argument("--onefile", action="store_true",
                    help="Single-file exe (convenient but ~30 s first-launch unpack)")
    ap.add_argument("--no-zip",  action="store_true", help="Skip zip creation")
    ap.add_argument("--clean",   action="store_true", help="Delete dist/ and build/ before building")
    args = ap.parse_args()

    if args.clean:
        for d in (DIST, BUILD):
            if d.exists():
                print(f"Removing {d} ...")
                _force_remove(d)

    _ensure_pyinstaller()

    out = _build(onefile=args.onefile)

    if not args.no_zip:
        print()
        zip_path = DIST / (out.stem + ".zip")
        _zip(out, zip_path)

    print("\nDone.")


if __name__ == "__main__":
    main()
