import copy
import json

import pytest
from pydantic import ValidationError
from studio.analysis import change_selection, import_analysis, prepare, snap, transcript, validate
from studio.models import Analysis, Client, Cut
from studio.storage import StudioError


def test_analysis_requires_complete_coverage(project, proposal):
    proposal["coverage"][0]["end"] = 50
    with pytest.raises(StudioError, match="complete"):
        validate(project, Analysis.model_validate(proposal))


def test_analysis_rejects_stale_inputs(project, proposal):
    proposal["input_digest"] = "old"
    with pytest.raises(StudioError, match="stale"):
        validate(project, Analysis.model_validate(proposal))


def test_analysis_requires_honest_shortage(project, proposal):
    proposal.pop("shortage_reason")
    with pytest.raises(StudioError, match="15-30"):
        validate(project, Analysis.model_validate(proposal))


def test_visual_cannot_cross_cut(project, proposal):
    proposal["visuals"] = [{"id": "g01", "source": proposal["candidates"][0]["source"], "timestamp": 39, "duration": 5, "type": "LIST", "spoken_context": "Exact words", "visual_concept": "Three steps", "target": "c01", "headline": "Steps"}]
    with pytest.raises(StudioError, match="crosses"):
        validate(project, Analysis.model_validate(proposal))


def test_fabricated_out_of_bounds_candidate(project, proposal):
    proposal["candidates"][0]["end_time"] = 400
    with pytest.raises(StudioError, match="envelope"):
        validate(project, Analysis.model_validate(proposal))


def test_snap_padding_preserves_whole_words(project):
    source = transcript(project).sources[0]
    cut = Cut(source=source.source, start=10.4, end=40.5, reason="complete thought")
    result = snap(cut, source, .08)
    assert result.start == pytest.approx(10.07)
    assert result.end == pytest.approx(40.88)
    assert all(not w.start < result.start < w.end and not w.start < result.end < w.end for w in source.words)


def test_duplicate_ideas_are_not_selected(project, proposal, tmp_path):
    other = copy.deepcopy(proposal["candidates"][0])
    other.update(id="c02", start_time=60.15, end_time=90.8)
    proposal["candidates"].append(other)
    path = tmp_path / "analysis.json"
    path.write_text(json.dumps(proposal))
    import_analysis(project, path)
    assert project.read("03_analysis/selection.json")["clips"] == ["c01"]
    change_selection(project, "clips", "replace", ["c01", "c02"])
    assert project.read("03_analysis/selection.json")["clips"] == ["c02"]


def test_brief_exports_every_chunk(project):
    prepare(project)
    coverage = project.read("03_analysis/coverage-required.json")
    assert coverage[0]["start"] == 0
    assert coverage[-1]["end"] == 120
    assert project.input_digest() in project.file("03_analysis/brief.md").read_text()
    assert "word119" in project.file("03_analysis/" + coverage[0]["file"]).read_text()


def test_nan_and_inverted_ranges_rejected():
    with pytest.raises(ValidationError):
        Cut(source="test", start=float("nan"), end=2, reason="x")
    with pytest.raises(ValidationError):
        Cut(source="test", start=5, end=2, reason="x")
    with pytest.raises(ValidationError):
        Client(name="Rui", shortform={"min_duration": 60, "max_duration": 30})
