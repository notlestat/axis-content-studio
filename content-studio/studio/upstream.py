"""Load the pinned video-use helpers without modifying their source files."""
from __future__ import annotations

import importlib.util
import os
import shutil
import subprocess
import sys
from functools import lru_cache
from pathlib import Path

from studio.storage import APP, StudioError


@lru_cache
def configure_media():
    """Prefer a configured binary; use the bundled libass build when necessary."""
    configured = os.environ.get("STUDIO_FFMPEG")
    binary = configured or shutil.which("ffmpeg")
    filters = ""
    if binary:
        filters = subprocess.run([binary, "-filters"], capture_output=True, text=True, check=True).stdout
    if " subtitles " not in filters and not configured:
        import imageio_ffmpeg
        binary = imageio_ffmpeg.get_ffmpeg_exe()
    if not binary or not shutil.which("ffprobe"):
        raise StudioError("Install ffmpeg and ffprobe, then run studio doctor")
    # video-use invokes ffmpeg by name. A private bin directory routes its calls.
    bindir = APP / "tools/runtime-bin"
    bindir.mkdir(parents=True, exist_ok=True)
    link = bindir / "ffmpeg"
    if link.is_symlink():
        if link.resolve() != Path(binary).resolve():
            link.unlink()
    if not link.exists():
        link.symlink_to(Path(binary).resolve())
    os.environ["PATH"] = str(bindir) + os.pathsep + os.environ.get("PATH", "")
    return str(link)


@lru_cache
def helper(name: str):
    configure_media()
    if name not in {"render", "transcribe", "pack_transcripts", "timeline_view", "grade"}:
        raise StudioError("Unknown video-use helper")
    root = APP / "vendor/video-use/helpers"
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    spec = importlib.util.spec_from_file_location("video_use_" + name, root / f"{name}.py")
    if spec is None or spec.loader is None:
        raise StudioError("video-use helper is missing")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def ffmpeg(args: list[str], cwd: Path | None = None):
    configure_media()
    return subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin", *args], cwd=cwd, capture_output=True, text=True, check=True)


def probe(path: Path):
    result = subprocess.run(["ffprobe", "-v", "error", "-show_format", "-show_streams", "-of", "json", str(path)], capture_output=True, text=True, check=True)
    import json
    data = json.loads(result.stdout)
    if not data.get("streams"):
        raise StudioError(f"No media streams: {path}")
    return data
