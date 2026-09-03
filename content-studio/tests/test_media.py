import json

import pytest
from studio.analysis import import_analysis
from studio.ingest import register
from studio.models import SourceTranscript, Transcript, Word
from studio.rendering import render_project
from studio.storage import ReviewRequired, Studio, sha256
from studio.transcription import save_transcript
from studio.upstream import ffmpeg, probe


@pytest.mark.media
def test_real_render_preserves_raw_and_creates_captioned_portrait(tmp_path):
    studio = Studio(tmp_path / "studio")
    studio.create_client("Render test")
    project = studio.create_project("render-test", "Integration", private_test=True)
    import yaml
    profile = project.profile.model_dump()
    profile["shortform"].update(min_duration=2, max_duration=10, clips_per_video=1, reframe="fit")
    (studio.client_path("render-test") / "client.yaml").write_text(yaml.safe_dump(profile))
    source = tmp_path / "source with ' quote.mp4"
    ffmpeg(["-y", "-f", "lavfi", "-i", "testsrc2=size=320x180:rate=30", "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000", "-t", "5", "-c:v", "libx264", "-c:a", "aac", "-pix_fmt", "yuv420p", str(source)])
    entry = register(project, source)
    before = sha256(project.file(entry["path"]))
    words = [Word(text=t, start=s, end=e) for t, s, e in [("A", .2, .5), ("test", .6, 1), ("of", 1.1, 1.5), ("captions.", 1.6, 2.2), ("Second", 2.4, 2.8), ("thought.", 2.9, 4.3)]]
    save_transcript(project, Transcript(sources=[SourceTranscript(source=entry["id"], source_sha256=entry["sha256"], duration=entry["duration"], provider="fixture", model="fixture", words=words)]))
    copy = {"hook": "Caption timing test", "title": "Caption test", "caption": "Synthetic test", "youtube_title": "Caption test", "description": "Synthetic test", "linkedin": "Synthetic test", "x_post": "Synthetic test", "alternative_hooks": ["a", "b", "c"], "alternative_titles": ["a", "b", "c"], "cta": "Review this test"}
    plan = {"input_digest": project.input_digest(), "strategy": "A synthetic integration test verifies real rendering and review guards.", "coverage": [{"source": entry["id"], "start": 0, "end": entry["duration"], "summary": "All test content"}], "shortage_reason": "Five second test", "candidates": [{"id": "c01", "source": entry["id"], "start_time": .2, "end_time": 4.3, "hook": "Caption test", "summary": "A fixture", "topic": "test", "scores": dict.fromkeys(["hook", "clarity", "standalone_value", "retention", "novelty", "overall"], 5), "reason_selected": "Exercise actual media pipeline", "copy": copy}]}
    path = tmp_path / "plan.json"
    path.write_text(json.dumps(plan))
    import_analysis(project, path)
    with pytest.raises(ReviewRequired):
        render_project(project)
    assert not project.file("07_final/shorts/01/clip.mp4").exists()
    result = render_project(project, auto=True)
    assert result["c01"]["qc"]["technical_pass"]
    assert sha256(project.file(entry["path"])) == before
    stream = probe(project.file("07_final/shorts/01/clip.mp4"))["streams"][0]
    assert (stream["width"], stream["height"]) == (1080, 1920)
    assert "Dialogue:" in project.file("05_shorts/c01/captions.ass").read_text()
    assert not project.approved("qc")
    again = render_project(project, auto=True)
    assert again["c01"]["rendered_at"] == result["c01"]["rendered_at"]
