from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING, List, Optional

if TYPE_CHECKING:
    from montra.tracker.config import TrackerConfig


class AppPaths:
    """
    Program-level standard directory paths relative to the repository root.
    Call AppPaths.init(root) once at application startup (from main.py).
    All directories are created on first access via ensure_dirs().
    """

    _root: Optional[Path] = None

    @classmethod
    def init(cls, root: Path) -> None:
        """Initialise with the repository root directory. Called once from main.py."""
        cls._root = Path(root).resolve()
        cls.ensure_dirs()

    @classmethod
    def _require_root(cls) -> Path:
        if cls._root is None:
            raise RuntimeError("AppPaths.init() has not been called")
        return cls._root

    # ── Standard directory properties ────────────────────────────────────────

    @classmethod
    @property
    def root(cls) -> Path:
        return cls._require_root()

    @classmethod
    @property
    def scripts_dir(cls) -> Path:
        return cls._require_root() / "scripts"

    @classmethod
    @property
    def rois_dir(cls) -> Path:
        return cls._require_root() / "rois"

    @classmethod
    @property
    def models_dir(cls) -> Path:
        return cls._require_root() / "models"

    @classmethod
    @property
    def tracking_configs_dir(cls) -> Path:
        return cls._require_root() / "configs" / "tracking"

    @classmethod
    @property
    def acquisition_configs_dir(cls) -> Path:
        return cls._require_root() / "configs" / "acquisition"

    @classmethod
    def ensure_dirs(cls) -> None:
        """Create all standard directories if they don't exist (idempotent)."""
        for d in [
            cls.scripts_dir,
            cls.rois_dir,
            cls.models_dir,
            cls.tracking_configs_dir,
            cls.acquisition_configs_dir,
        ]:
            d.mkdir(parents=True, exist_ok=True)

    # ── Named resource helpers ────────────────────────────────────────────────

    @classmethod
    def list_tracking_configs(cls) -> List[str]:
        """Return stems of *.json files in configs/tracking/, sorted alphabetically."""
        return sorted(p.stem for p in cls.tracking_configs_dir.glob("*.json"))

    @classmethod
    def load_tracking_config(cls, name: str) -> "TrackerConfig":
        from montra.tracker.config import TrackerConfig
        return TrackerConfig.load(cls.tracking_configs_dir / f"{name}.json")

    @classmethod
    def save_tracking_config(cls, config: "TrackerConfig", name: str) -> None:
        config.save(cls.tracking_configs_dir / f"{name}.json")

    @classmethod
    def list_acquisition_configs(cls) -> List[str]:
        return sorted(p.stem for p in cls.acquisition_configs_dir.glob("*.json"))

    @classmethod
    def list_scripts(cls) -> List[str]:
        return sorted(p.stem for p in cls.scripts_dir.glob("*.acq"))

    @classmethod
    def list_rois(cls) -> List[str]:
        return sorted(p.stem for p in cls.rois_dir.glob("*.json"))

    @classmethod
    def load_rois(cls, name: str) -> list:
        path = cls.rois_dir / f"{name}.json"
        return json.loads(path.read_text(encoding="utf-8"))

    @classmethod
    def save_rois(cls, rois: list, name: str) -> None:
        path = cls.rois_dir / f"{name}.json"
        path.write_text(json.dumps(rois, indent=2), encoding="utf-8")
