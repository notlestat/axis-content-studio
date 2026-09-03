from __future__ import annotations

import contextlib
import fcntl
import hashlib
import json
import os
import re
import tempfile
import time
import unicodedata
from datetime import datetime, timezone
from pathlib import Path

import yaml

from studio.models import Client, Settings

APP = Path(__file__).resolve().parents[1]
PROJECT_DIRS = ("01_raw", "02_transcript", "03_analysis", "04_longform", "05_shorts", "06_copy", "07_final", "logs")
MEDIA_EXT = {".mp4", ".mov", ".mkv", ".wav", ".mp3"}


class StudioError(Exception):
    pass


class ReviewRequired(StudioError):
    pass


def now():
    return datetime.now(timezone.utc).isoformat()


def slug(value: str) -> str:
    text = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode().lower()
    text = re.sub(r"[^a-z0-9]+", "-", text).strip("-")[:80].rstrip("-")
    if not text:
        raise StudioError("Name needs at least one letter or number")
    return text


def identifier(value: str) -> str:
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,79}", value):
        raise StudioError(f"Invalid identifier: {value!r}")
    return value


def contained(base: Path, path: Path) -> Path:
    base = base.resolve()
    # Reject symlinks even when they happen to point back inside the project.
    absolute = path.absolute()
    if not absolute.is_relative_to(base):
        raise StudioError(f"Path escapes {base}: {path}")
    for part in [absolute, *absolute.parents]:
        if part == base:
            break
        if part.is_symlink():
            raise StudioError(f"Symlinks are not allowed in project paths: {part}")
    if not absolute.resolve().is_relative_to(base):
        raise StudioError(f"Path escapes {base}: {path}")
    return absolute


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(4 * 1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def digest(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def read_json(path: Path, default=None):
    return json.loads(path.read_text()) if path.exists() else default


def atomic_text(path: Path, text: str):
    if path.is_symlink():
        raise StudioError(f"Refusing to replace symlink {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp = tempfile.mkstemp(prefix=".studio-", dir=path.parent)
    try:
        with os.fdopen(fd, "w") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        os.replace(temp, path)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)


def write_json(path: Path, data):
    atomic_text(path, json.dumps(data, indent=2, ensure_ascii=False, allow_nan=False) + "\n")


class Studio:
    def __init__(self, root: Path | None = None):
        self.root = (root or Path(os.environ.get("STUDIO_ROOT", APP))).resolve()

    def client_path(self, client: str):
        return contained(self.root, self.root / "clients" / identifier(client))

    def client(self, client: str) -> Client:
        path = contained(self.root, self.client_path(client) / "client.yaml")
        if not path.exists():
            raise StudioError(f"Client {client!r} does not exist. Use studio client create.")
        return Client.model_validate(yaml.safe_load(path.read_text()))

    def settings(self) -> Settings:
        path = self.root / "config/studio.yaml"
        return Settings.model_validate(yaml.safe_load(path.read_text()) or {}) if path.exists() else Settings()

    def create_client(self, name: str):
        key = slug(name)
        path = self.client_path(key)
        if path.exists():
            raise StudioError(f"Client already exists: {key}")
        for directory in ["brand/logos", "brand/assets", "brand/references", "projects"]:
            (path / directory).mkdir(parents=True, exist_ok=True)
        atomic_text(path / "client.yaml", yaml.safe_dump(Client(name=name).model_dump(), sort_keys=False))
        return key

    def create_project(self, client: str, title: str, private_test: bool = False):
        self.client(client)
        key = slug(title)
        path = contained(self.root, self.client_path(client) / "projects" / key)
        if path.exists():
            raise StudioError(f"Project already exists: {key}")
        for d in PROJECT_DIRS:
            (path / d).mkdir(parents=True)
        write_json(path / "project.json", {"title": title, "client": client, "created_at": now(), "private_test": private_test})
        return Project(self, client, path)

    def project(self, client: str, key: str | None = None):
        self.client(client)
        parent = contained(self.root, self.client_path(client) / "projects")
        if key is None or key == "latest":
            candidates = [p for p in parent.iterdir() if p.is_dir() and (p / "project.json").is_file()]
            if not candidates:
                raise StudioError(f"No projects for {client}")
            path = max(candidates, key=lambda p: read_json(p / "project.json")["created_at"])
        else:
            path = parent / identifier(key)
        path = contained(self.root, path)
        if not (path / "project.json").exists():
            raise StudioError(f"Project not found: {path.name}")
        return Project(self, client, path)


class Project:
    def __init__(self, studio: Studio, client: str, path: Path):
        self.studio, self.client_slug, self.path = studio, client, path

    @property
    def profile(self):
        return self.studio.client(self.client_slug)

    def file(self, rel: str):
        return contained(self.path, self.path / rel)

    def write(self, rel: str, data):
        if Path(rel).parts[0] == "01_raw":
            raise StudioError("The raw directory is immutable to studio writers")
        write_json(self.file(rel), data)

    def text(self, rel: str, data: str):
        if Path(rel).parts[0] == "01_raw":
            raise StudioError("The raw directory is immutable to studio writers")
        atomic_text(self.file(rel), data)

    def read(self, rel: str, default=None):
        return read_json(self.file(rel), default)

    @contextlib.contextmanager
    def lock(self):
        for parent, dirs, files in os.walk(self.path, followlinks=False):
            for name in dirs + files:
                p = Path(parent) / name
                if p.is_symlink():
                    raise StudioError(f"Symlinks are not allowed inside a project: {p}")
                if p.is_file() and "01_raw" not in p.relative_to(self.path).parts and p.stat().st_nlink > 1:
                    raise StudioError(f"Working file has multiple hard links: {p}")
        with self.file("logs/project.lock").open("a") as f:
            try:
                fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as e:
                raise StudioError("This project is already being processed") from e
            try:
                yield
            finally:
                fcntl.flock(f, fcntl.LOCK_UN)

    def event(self, stage: str, **fields):
        path = self.file("logs/events.jsonl")
        with path.open("a") as f:
            f.write(json.dumps({"time": now(), "stage": stage, **fields}, allow_nan=False) + "\n")

    @contextlib.contextmanager
    def timed(self, stage: str):
        start = time.monotonic()
        try:
            yield
        except Exception as exc:
            self.event(stage, status="failed", seconds=round(time.monotonic() - start, 3), error=str(exc)[:500])
            raise
        else:
            self.event(stage, status="complete", seconds=round(time.monotonic() - start, 3))

    def ledger(self, category: str, provider: str, model: str, cost_usd: float | None, **fields):
        self.event("usage", category=category, provider=provider, model=model, estimated_cost_usd=cost_usd, **fields)

    def input_digest(self):
        return digest({"profile": self.profile.model_dump(), "settings": self.studio.settings().model_dump(), "sources": self.read("sources.json", []), "transcript": self.read("02_transcript/transcript.json")})

    def review_digest(self, stage: str):
        data = {"inputs": self.input_digest(), "stage": stage}
        if stage != "transcript":
            data["analysis"] = self.read("03_analysis/analysis.json")
            data["selection"] = self.read("03_analysis/selection.json")
        if stage == "qc":
            data["renders"] = self.read("logs/render-manifest.json")
            data["current_render_hashes"] = {key: sha256(self.file(item["path"])) if self.file(item["path"]).exists() else None for key, item in (data["renders"] or {}).items()}
        return digest(data)

    def approved(self, stage: str):
        approval = self.read(f"logs/approval-{stage}.json", {})
        return approval.get("digest") == self.review_digest(stage) and approval.get("decision") == "approved"

    def approve(self, stage: str, note: str):
        self.write(f"logs/approval-{stage}.json", {"digest": self.review_digest(stage), "decision": "approved", "note": note, "at": now()})
        self.event("review", review_stage=stage, decision="approved", note=note)

    def require(self, stage: str, auto: bool = False):
        if auto:
            self.event("review", review_stage=stage, decision="bypassed", reason="explicit --auto experiment")
        elif not self.approved(stage):
            raise ReviewRequired(f"Review {stage}, then run: studio approve {self.client_slug} {self.path.name} {stage} --note 'Your review notes'")
