import json

import pytest
from studio.analysis import import_analysis, prepare
from studio.ingest import register, verify_sources
from studio.storage import ReviewRequired, StudioError, sha256


def test_raw_never_overwritten(project, tmp_path):
    first = project.read("sources.json")[0]
    raw = project.file(first["path"])
    before = sha256(raw)
    other = tmp_path / "other" / "original.mp4"
    other.parent.mkdir()
    other.write_bytes(b"another distinct take")
    second = register(project, other)
    assert first["path"] != second["path"]
    assert sha256(raw) == before
    with pytest.raises(StudioError, match="immutable"):
        project.text(first["path"], "overwrite")


def test_changed_source_is_refused(project):
    path = project.file(project.read("sources.json")[0]["path"])
    path.write_bytes(b"externally changed")
    with pytest.raises(StudioError, match="changed"):
        verify_sources(project)
    with pytest.raises(StudioError, match="changed"):
        register(project, path)


def test_ingest_is_idempotent(project):
    entry = project.read("sources.json")[0]
    assert register(project, project.file(entry["path"])) == entry
    assert len(project.read("sources.json")) == 1


@pytest.mark.parametrize("value", ["../escape", "/tmp/foo", "rui/fu", "", "a;rm -rf b"])
def test_client_identifier_cannot_escape(project, value):
    with pytest.raises(StudioError):
        project.studio.client_path(value)


def test_symlink_output_rejected(project, tmp_path):
    victim = tmp_path / "victim"
    victim.write_text("safe")
    project.file("04_longform/innocent.mp4").symlink_to(victim)
    with pytest.raises(StudioError, match="Symlinks"):
        with project.lock():
            pass
    assert victim.read_text() == "safe"


def test_hardlinked_working_file_rejected(project):
    victim = project.file(project.read("sources.json")[0]["path"])
    project.file("04_longform/output.mp4").hardlink_to(victim)
    with pytest.raises(StudioError, match="hard links"):
        with project.lock():
            pass


def test_review_is_bound_to_inputs(project, proposal, tmp_path):
    prepare(project)
    path = tmp_path / "analysis.json"
    path.write_text(json.dumps(proposal))
    import_analysis(project, path)
    project.approve("plan", "Read the whole plan")
    assert project.approved("plan")
    selection = project.read("03_analysis/selection.json")
    selection["clips"] = []
    project.write("03_analysis/selection.json", selection)
    assert not project.approved("plan")
    with pytest.raises(ReviewRequired):
        project.require("plan")


def test_auto_never_creates_human_approval(project):
    project.require("transcript", auto=True)
    assert not project.approved("transcript")
    assert "bypassed" in project.file("logs/events.jsonl").read_text()


def test_lock_blocks_second_writer(project):
    with project.lock(), pytest.raises(StudioError, match="already"):
        with project.lock():
            pass
