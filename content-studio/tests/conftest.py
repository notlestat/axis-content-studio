
import pytest
from studio.ingest import register
from studio.models import SourceTranscript, Transcript, Word
from studio.storage import Studio
from studio.transcription import save_transcript


@pytest.fixture
def project(tmp_path, monkeypatch):
    studio = Studio(tmp_path / "studio")
    client = studio.create_client("Test Client")
    project = studio.create_project(client, "Episode 1", private_test=True)
    source = tmp_path / "original.mp4"
    source.write_bytes(b"untouched test media")
    metadata = {"format": {"duration": "120"}, "streams": [{"codec_type": "video", "width": 1920, "height": 1080}, {"codec_type": "audio"}]}
    monkeypatch.setattr("studio.ingest.probe", lambda _: metadata)
    item = register(project, source)
    words = [Word(text=f"word{i}.", start=i + .15, end=i + .8) for i in range(120)]
    save_transcript(project, Transcript(sources=[SourceTranscript(source=item["id"], source_sha256=item["sha256"], duration=120, provider="fixture", model="fixture", words=words)]))
    return project


@pytest.fixture
def proposal(project):
    key = project.read("sources.json")[0]["id"]
    return {"input_digest": project.input_digest(), "strategy": "Preserve a complete useful idea with natural delivery and accurate captions.", "coverage": [{"source": key, "start": 0, "end": 120, "summary": "Entire synthetic source covered"}], "shortage_reason": "Short fixture supports only one distinct moment", "candidates": [{"id": "c01", "source": key, "start_time": 10.15, "end_time": 40.8, "hook": "An exact opening", "summary": "A complete thought", "topic": "one", "scores": dict.fromkeys(["hook", "clarity", "standalone_value", "retention", "novelty", "overall"], 8), "reason_selected": "Specific useful thought", "copy": {"hook": "An exact opening", "title": "A lesson", "caption": "An honest description.", "youtube_title": "A useful lesson", "description": "A description grounded in the clip.", "linkedin": "A lesson from this conversation.", "x_post": "A specific lesson.", "alternative_hooks": ["One", "Two", "Three"], "alternative_titles": ["A", "B", "C"], "cta": "What would you do?"}}]}
