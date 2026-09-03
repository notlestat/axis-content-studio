import pytest
from studio.analysis import transcript
from studio.captions import ass_time, build_ass, output_words
from studio.models import Captions, Cut
from studio.reporting import costs


def test_caption_timing_uses_output_offsets(project, tmp_path):
    source = transcript(project).sources[0]
    cuts = [Cut(source=source.source, start=10.07, end=12.88, reason="first"), Cut(source=source.source, start=50.07, end=52.88, reason="second")]
    words = output_words(cuts, transcript(project))
    assert words[0]["start"] == pytest.approx(.08)
    assert words[3]["start"] == pytest.approx(2.89)
    path = tmp_path / "captions.ass"
    result = build_ass(cuts, transcript(project), Captions(), (1080, 1920), "#A8D5BA", path)
    assert result["safe_zone"]["margin_vertical"] == 576
    assert max(c["lines"] for c in result["cues"]) <= 2
    assert "PlayResY: 1920" in path.read_text()


def test_timestamp_rounding_carries_minutes():
    assert ass_time(59.999) == "0:01:00.00"


def test_unknown_cost_not_silently_zero(project):
    project.ledger("transcription", "local", "small.en", 0, api_calls=0)
    project.ledger("llm", "codex-session", "session", None, api_calls=0)
    summary = costs(project)
    assert summary["estimated_total_usd"] is None
    assert summary["known_api_cost_usd"] == 0


def test_api_attempt_and_result_count_once(project):
    project.ledger("transcription", "elevenlabs", "scribe_v1", None, api_calls=1, request_id="a", status="attempt")
    project.ledger("transcription", "elevenlabs", "scribe_v1", .5, api_calls=0, request_id="a", status="result")
    assert costs(project)["estimated_total_usd"] == .5
    assert costs(project)["api_calls"] == 1


def test_failed_api_call_remains_unpriced(project):
    project.ledger("transcription", "elevenlabs", "scribe_v1", None, api_calls=1, request_id="a", status="attempt")
    assert costs(project)["estimated_total_usd"] is None


def test_hyphenated_asr_words_keep_compound_and_timing():
    from studio.captions import output_words
    from studio.models import Cut, SourceTranscript, Transcript, Word
    trans = Transcript(sources=[SourceTranscript(source='s', source_sha256='test', duration=3,
        provider='fixture', model='fixture', words=[Word(text='tried', start=.2, end=.5),
        Word(text='-and', start=.5, end=.7), Word(text='-true', start=.7, end=1)])])
    words = output_words([Cut(source='s', start=0, end=2, reason='Keep compound')], trans)
    assert words == [{'text': 'tried-and-true', 'start': .2, 'end': 1}]
