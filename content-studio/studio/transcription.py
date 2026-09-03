from __future__ import annotations

import json
import tempfile
from pathlib import Path

from studio.ingest import verify_sources
from studio.models import SourceTranscript, Transcript, Word
from studio.storage import Project, StudioError, digest
from studio.upstream import helper


def save_transcript(project: Project, trans: Transcript):
    entries = verify_sources(project)
    if {t.source for t in trans.sources} != set(entries):
        raise StudioError("Transcript must contain every registered source exactly once")
    if len(trans.sources) != len(entries):
        raise StudioError("Duplicate source transcript")
    for source in trans.sources:
        if source.source_sha256 != entries[source.source]["sha256"] or abs(source.duration - entries[source.source]["duration"]) > .25:
            raise StudioError("Transcript hash or duration does not match its source")
    project.write("02_transcript/transcript.json", trans.model_dump())
    packer = helper("pack_transcripts")
    packed = []
    for source in trans.sources:
        words = [w.model_dump() for w in source.words]
        phrases = packer.group_into_phrases(words, .5)
        packed.append((source.source, source.duration, phrases))
        project.write(f"02_transcript/transcripts/{source.source}.json", {"words": words})
    text = packer.render_markdown(packed, .5)
    project.text("02_transcript/transcript.md", text)
    return trans


def import_transcript(project: Project, path: Path):
    return save_transcript(project, Transcript.model_validate(json.loads(path.read_text())))


def transcribe(project: Project, provider: str | None = None, model: str | None = None):
    entries = verify_sources(project)
    settings = project.studio.settings()
    provider = provider or settings.transcription
    model = model or (settings.local_model if provider == "local" else "scribe_v1")
    if provider == "elevenlabs" and model != "scribe_v1":
        raise StudioError("The vendored video-use Scribe adapter supports scribe_v1 only")
    previous = project.read("02_transcript/transcript.json")
    cached_sources = {s["source"]: s for s in (previous or {}).get("sources", [])}
    output = []
    for key, entry in entries.items():
        cached = cached_sources.get(key, {})
        if (cached.get("source_sha256") == entry["sha256"] and cached.get("provider") == provider
                and cached.get("model") == model and cached.get("language") == settings.language
                and cached.get("audio_track", 0) == settings.audio_track):
            output.append(SourceTranscript.model_validate(cached_sources[key]))
            continue
        cache_key = digest({"source": entry["sha256"], "provider": provider, "model": model, "language": settings.language, "track": settings.audio_track})
        cache = project.file(f"02_transcript/cache/{cache_key}.json")
        if cache.exists():
            output.append(SourceTranscript.model_validate_json(cache.read_text()))
            continue
        video = project.file(entry["path"])
        upstream = helper("transcribe")
        with project.timed("transcribe"), tempfile.TemporaryDirectory(prefix="asr-", dir=project.file("logs")) as tmp:
            audio = Path(tmp) / "audio.wav"
            upstream.extract_audio(video, audio, settings.audio_track)
            if upstream.peak_dbfs(audio) < -60:
                raise StudioError("Selected audio track is silent. Choose audio_track in config/studio.yaml.")
            if provider == "elevenlabs":
                import os
                api_key = os.environ.get("ELEVENLABS_API_KEY")
                if not api_key:
                    raise StudioError("Export ELEVENLABS_API_KEY or select --provider local. Do not paste keys into client files.")
                project.ledger("transcription", "elevenlabs", model, None, api_calls=1, status="attempt", minutes=entry["duration"] / 60, request_id=cache_key)
                payload = upstream.call_scribe(audio, api_key, settings.language)
                project.write(f"02_transcript/provider/{cache_key}.json", payload)
                words = [Word(text=w["text"].strip(), start=w["start"], end=w["end"], type=w["type"], speaker_id=w.get("speaker_id")) for w in payload.get("words", []) if w.get("type") in {"word", "audio_event"} and w.get("end", 0) > w.get("start", 0) and w.get("text", "").strip()]
                rate = settings.rates.transcription_per_minute_usd
                project.ledger("transcription", "elevenlabs", model, rate * entry["duration"] / 60 if rate is not None else None, api_calls=0, status="result", request_id=cache_key, minutes=entry["duration"] / 60)
                warnings = []
            elif provider == "local":
                try:
                    from faster_whisper import WhisperModel
                except ImportError as e:
                    raise StudioError("Install local transcription: .venv/bin/pip install -e '.[local]'") from e
                asr = WhisperModel(model, device="cpu", compute_type="int8", cpu_threads=6, download_root=str(project.studio.root / "tools/cache/whisper"))
                segments, info = asr.transcribe(str(audio), language=settings.language, word_timestamps=True, vad_filter=True, condition_on_previous_text=False, beam_size=5)
                words = []
                last_progress = 0.0
                for segment in segments:
                    words.extend(Word(text=w.word.strip(), start=w.start, end=w.end) for w in segment.words or [] if w.word.strip() and w.end > w.start)
                    if segment.end - last_progress >= 120:
                        print(f"  {key}: transcribed {segment.end:.0f}/{entry['duration']:.0f}s", flush=True)
                        last_progress = segment.end
                project.ledger("transcription", "local", model, 0, api_calls=0, minutes=entry["duration"] / 60)
                warnings = ["Local Whisper may omit fillers and has no speaker diarization. Verify names, numbers and cut edges against the audio."]
            else:
                raise StudioError(f"Unknown transcription provider: {provider}")
        item = SourceTranscript(source=key, source_sha256=entry["sha256"], duration=entry["duration"], provider=provider, model=model, language=settings.language, audio_track=settings.audio_track, words=words, warnings=warnings)
        project.write(str(cache.relative_to(project.path)), item.model_dump())
        output.append(item)
    return save_transcript(project, Transcript(sources=output))
