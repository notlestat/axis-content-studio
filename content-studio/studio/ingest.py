from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from urllib.parse import urlparse

from studio.storage import MEDIA_EXT, Project, StudioError, identifier, sha256, slug
from studio.upstream import configure_media, probe


def sources(project: Project):
    return {s["id"]: s for s in project.read("sources.json", [])}


def verify_sources(project: Project):
    records = sources(project)
    if not records:
        raise StudioError("No media. Place footage in 01_raw or use studio ingest.")
    for entry in records.values():
        path = project.file(entry["path"])
        if not path.is_file() or sha256(path) != entry["sha256"]:
            raise StudioError(f"Raw source changed or is missing: {entry['path']}. Restore it before processing.")
    return records


def register(project: Project, path: Path, origin: dict | None = None):
    if path.suffix.lower() not in MEDIA_EXT:
        raise StudioError(f"Unsupported source extension: {path.suffix}")
    path = path.absolute()
    if not path.is_file() or path.is_symlink():
        raise StudioError("Source must be a regular file, not a symlink")
    fingerprint = sha256(path)
    existing = sources(project)
    # Duplicate content, even with a different name, is the same take.
    for entry in existing.values():
        if entry["sha256"] == fingerprint:
            return entry
        if path.is_relative_to(project.path) and entry["path"] == str(path.relative_to(project.path)):
            raise StudioError("Previously registered source changed. Restore the original.")
    metadata = probe(path)
    duration = float(metadata["format"]["duration"])
    if duration <= 0:
        raise StudioError("Source duration must be positive")
    key = identifier(f"{slug(path.stem)[:50]}-{fingerprint[:12]}")
    if path.parent == project.file("01_raw"):
        destination = project.file("01_raw/" + path.name)
    else:
        destination = project.file(f"01_raw/{key}{path.suffix.lower()}")
        # Exclusive creation guarantees an ingest never overwrites a raw file.
        with path.open("rb") as source, destination.open("xb") as target:
            shutil.copyfileobj(source, target, 4 * 1024 * 1024)
        if sha256(destination) != fingerprint:
            raise StudioError("Source changed during copy; copied file retained for inspection")
    entry = {"id": key, "path": str(destination.relative_to(project.path)), "original_name": path.name, "sha256": fingerprint, "duration": duration, "bytes": destination.stat().st_size, "origin": origin or {"kind": "local", "path": str(path)}, "probe": metadata}
    existing[key] = entry
    project.write("sources.json", list(existing.values()))
    project.event("ingest", source=key, bytes=entry["bytes"])
    return entry


def inventory(project: Project):
    for file in sorted(project.file("01_raw").iterdir()):
        if file.suffix.lower() in MEDIA_EXT:
            register(project, file)
    return verify_sources(project)


def youtube(project: Project, url: str):
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or parsed.hostname not in {"youtube.com", "www.youtube.com", "m.youtube.com", "youtu.be"}:
        raise StudioError("Supply a public YouTube video URL")
    for entry in sources(project).values():
        if entry["origin"].get("url") == url:
            verify_sources(project)
            return entry
    configure_media()
    with tempfile.TemporaryDirectory(prefix="download-", dir=project.file("logs")) as temp:
        template = str(Path(temp) / "%(id)s.%(ext)s")
        command = [sys.executable, "-m", "yt_dlp", "--no-playlist", "--no-overwrites", "--js-runtimes", "node", "--write-info-json", "--no-progress", "-f", "bv*[height<=1080]+ba/b[height<=1080]", "--merge-output-format", "mp4", "-o", template, "--", url]
        with project.file("logs/download.log").open("a") as log:
            result = subprocess.run(command, stdout=log, stderr=log, env=os.environ.copy())
        if result.returncode:
            raise StudioError("YouTube download failed. See logs/download.log. No login or cookies were used; a local source can be ingested instead.")
        files = [p for p in Path(temp).iterdir() if p.suffix.lower() in MEDIA_EXT]
        if len(files) != 1:
            raise StudioError("Download did not produce exactly one media file")
        from studio.storage import read_json
        info = read_json(next(Path(temp).glob("*.info.json")))
        origin = {"kind": "youtube", "url": url, "id": info.get("id"), "title": info.get("title"), "uploader": info.get("uploader"), "license": info.get("license"), "duration": info.get("duration")}
        return register(project, files[0], origin)
