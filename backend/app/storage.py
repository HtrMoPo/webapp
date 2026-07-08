"""Local disk staging for files attached to a draft model version, until the
version is published to Zenodo (so a failed Zenodo call doesn't lose uploads)."""

from pathlib import Path

from app.config import get_settings


def draft_dir(version_id: int) -> Path:
    settings = get_settings()
    base = Path(settings.database_path).parent / "uploads" / str(version_id)
    base.mkdir(parents=True, exist_ok=True)
    return base


def delete_draft_file(version_id: int, filename: str) -> None:
    path = draft_dir(version_id) / filename
    path.unlink(missing_ok=True)


def list_draft_files(version_id: int) -> list[Path]:
    d = draft_dir(version_id)
    return sorted(p for p in d.iterdir() if p.is_file())


def cleanup_draft(version_id: int) -> None:
    import shutil

    settings = get_settings()
    base = Path(settings.database_path).parent / "uploads" / str(version_id)
    shutil.rmtree(base, ignore_errors=True)
