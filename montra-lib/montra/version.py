"""
Bump __version__ before tagging a release.  The git commit hash is
captured at import time so any produced H5 files carry exact provenance.
"""

from __future__ import annotations

__version__ = "0.0.1"


def _git_hash() -> str:
    """Return the short HEAD commit hash, or 'unversioned' outside a git repo."""
    try:
        import subprocess
        r = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True, text=True, timeout=2,
        )
        if r.returncode == 0:
            return r.stdout.strip()
    except Exception:
        pass
    return "unversioned"


__git_hash__: str = _git_hash()


