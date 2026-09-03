# Upstream review and reuse

Inspected on 2026-09-02 before implementation.

## video-use

Repository: https://github.com/browser-use/video-use
Commit: 9575612f066aa517354790a645fd90f9f95a743b
License: MIT, copyright 2026 Browser Use. Retained in vendor/video-use/LICENSE.

Read README.md, SKILL.md, install.md, pyproject.toml, all six helpers, and the
render/transcription contracts. This is an agent editing workflow, not a callable
one-click clip detector.

Studio reuses the actual helper code:

- transcribe.extract_audio, peak_dbfs and call_scribe for ElevenLabs Scribe v1.
- pack_transcripts.group_into_phrases and render_markdown for reading transcripts.
- render.extract_segment, concat_segments and build_final_composite for editing.
- render.apply_loudnorm_two_pass for -14 LUFS, -1 dBTP, 11 LU loudness targets.
- timeline_view.py for filmstrips, waveforms and output-word labels at cuts.
- grade.py is retained as the render helper's dependency. Automatic grading is
  not applied indiscriminately; studio defaults preserve source colour.

One small upstream modification is recorded in vendor/video-use/STUDIO-PATCHES.md.
The extraction helper accepts an audio-track argument and normalizes channels to
stereo. This prevents mismatched audio tracks in multi-source concat.

Studio's adapter supplies crop/fit filters, output sizes, explicit full-resolution
ASS subtitles and temporary paths safe for the upstream concat parser. It does
not replace the render pipeline. Captions remain the last compositing operation.
The upstream subtitle builder is not used because it hardcodes a two-word uppercase
preset; studio needs multiple reusable client presets and full-resolution safe zones.

The upstream Scribe-only preference is retained as the preferred verbatim service.
The local Whisper option is an explicit studio extension for operation without keys.
It has word timing, but may omit fillers and does not diarize speakers. The report
and transcript record that limitation. Do not run filler deletion from this data
without listening.

Animation opportunities map to video-use animation slots. Each slot has source,
rendered asset, metadata and a content fingerprint. HyperFrames handles HTML/GSAP
cards locally; a Remotion render may be attached to the same slot contract. No
animation services, account or cloud renderer are required.

## AutoClip

Repository: https://github.com/zhouxiaoka/autoclip
Commit: 17100c05252b9a947ea1a857f8d0ea4f3af2317b
License: MIT, copyright 2024 AutoClip Team. License in docs/licenses/AutoClip-MIT.txt.

Read README-EN.md and backend/pipeline/step1_outline.py, step2_timeline.py,
step3_scoring.py, step5_clustering.py, plus the business timestamp and recommendation
prompts. The relevant sequence is whole-transcript chunking, outlines, complete
moment boundaries, model assessment, title generation and topic grouping.

Studio uses that approach with original orchestration and prompts. No AutoClip
runtime code or business prompts were copied. AutoClip's business timing prompts
suggest multi-minute segments, so their duration rules are not reused for Shorts.
Studio uses the client duration limits. Stable IDs bind judgments to candidates.
The default selection removes overlapping moments and repeated topic labels.
Semantic topic grouping is supplied by Codex; it is not a viral-score heuristic.

No FastAPI, React, Celery, Redis, accounts, uploader or infrastructure is installed.

## External contracts

- Scribe is called only through the inspected video-use helper at the exact
  endpoint defined there. ELEVENLABS_API_KEY is read from the environment.
- yt-dlp is a subprocess with an argument list, no shell interpolation. It downloads
  one public video, with no cookies or account access. A failed download is an error,
  not an empty successful project.
- Local Whisper runs in the project virtual environment and caches its model under
  tools/cache/whisper. The first model download needs network access.
- Editorial analysis uses this Codex session. The CLI exports a full brief and JSON
  schema and validates the response. No undocumented LLM endpoint is invented.
- HyperFrames 0.8.26 and GSAP 3.15.0 are pinned in tools/graphics/package-lock.json.
  HyperFrames init/check/render commands run locally with telemetry disabled.
  The installed soft-blur-in registry component supplies the reveal primitive.
  HyperFrames' Apache-2.0 license is retained in docs/licenses/HyperFrames-Apache-2.0.txt;
  the component source remains in templates/graphic-slot/compositions/components/.
- No provider prices are hardcoded. Rates in config/studio.yaml are supplied by the
  operator. Missing rates and inaccessible Codex usage are null, never guessed.
