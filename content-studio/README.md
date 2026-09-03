# Axis content studio

A local production workspace for a one-person editing business. Python manages
files, media operations and review state. Codex reads the complete transcript and
makes editorial decisions. Everything stays in client project folders.

There is no server, frontend, account system, billing or publishing integration.

## First client

Install dependencies using the repository README first. On the original studio
Mac, these dependencies are already installed. From the repository root:

```sh
cd content-studio
source .venv/bin/activate
studio doctor
studio client create 'Rui Fu'
studio project create rui-fu 'AI Business Podcast'
```

Edit `clients/rui-fu/client.yaml` to save Rui's preferences. Longform defaults to
disabled; set `longform.enabled: true` when the client wants a YouTube edit.
`target_duration`, short durations and all timestamps are seconds. Null longform
target duration means preserve the editorially useful length.

Add media with either command:

```sh
studio ingest rui-fu ai-business-podcast --file '/absolute/path/episode.mp4'
studio ingest rui-fu ai-business-podcast --youtube 'https://www.youtube.com/watch?v=VIDEO_ID'
```

Or copy the source into `clients/rui-fu/projects/ai-business-podcast/01_raw/`.
Then tell Codex, **"Process Rui's latest project."** The parent AGENTS.md defines
how Codex resumes the workflow. It reads Rui's profile every time.

Run it yourself:

```sh
studio process rui-fu
```

This resumes the newest project and stops at the next required review. It does not
pretend to be an unattended LLM service. In the normal workflow Codex authors and
imports the editorial plan, and you approve the choices.

## Review and render your first project

```sh
# 1. Review word-timed ASR. Correct names/numbers in transcript.json if needed.
studio review rui-fu ai-business-podcast transcript
# After editing the JSON, rebuild the readable transcript through this importer:
studio transcribe rui-fu ai-business-podcast --import-json clients/rui-fu/projects/ai-business-podcast/02_transcript/transcript.json
studio approve rui-fu ai-business-podcast transcript --note 'Checked names, numbers and timing against source'

# 2. Ask Codex to read this brief and every chunk, then write the analysis JSON.
studio analyze prepare rui-fu ai-business-podcast
studio analyze import rui-fu ai-business-podcast clients/rui-fu/projects/ai-business-podcast/03_analysis/analysis-proposal.json
studio review rui-fu ai-business-podcast plan

# 3. Edit the selected set. These examples use IDs from your generated plan.
studio clips reject rui-fu ai-business-podcast c02
studio clips approve rui-fu ai-business-podcast c07
studio clips replace rui-fu ai-business-podcast c03 c09
studio graphics reject rui-fu ai-business-podcast g02
studio review rui-fu ai-business-podcast graphics

# 4. Approve the current selections after reviewing them.
studio approve rui-fu ai-business-podcast plan --note 'Approved the keep ranges and selected shorts'
studio approve rui-fu ai-business-podcast graphics --note 'Approved the chosen concepts and timing'
studio render rui-fu ai-business-podcast

# 5. Technical QC is automatic. Generate visual evidence and watch/listen too.
studio qc rui-fu ai-business-podcast
studio qc rui-fu ai-business-podcast --inspect c01
studio qc rui-fu ai-business-podcast --inspect longform
studio approve rui-fu ai-business-podcast qc --note 'Watched every output, checked cuts, sync, captions and graphics'
studio report rui-fu ai-business-podcast
```

Approve only after doing the stated check. IDs are stable within an analysis.
Replacing a clip may need copy or new visual opportunities from Codex. Edit the
proposal and reimport it. Imports recalculate the default selection, so apply
your final clip choices afterwards.

Approvals expire when relevant inputs or choices change. A render cannot use a
stale analysis. Raw files are hashed and checked before processing. Symlinks and
hardlinked working files are refused. Originals are never output destinations.

`--auto` bypasses review checkpoints for experiments:

```sh
studio process rui-fu ai-business-podcast --auto
studio render rui-fu ai-business-podcast --auto
```

The first command still needs a real Codex-authored analysis if none exists. It
exports a brief and exits 2. Neither command marks experimental output ready to
publish. All normal review commands remain available afterwards.

## Files

```text
content-studio/
  clients/<client>/
    client.yaml
    brand/{logos,assets,references}/
    projects/<project>/
      project.json
      sources.json
      01_raw/           original media, never modified
      02_transcript/    transcript.json, transcript.md, per-source ASR cache
      03_analysis/      brief, coverage chunks, analysis, candidates, selection
                        visual opportunities, animation slots, review notes
      04_longform/      EDL, output transcript, framing and QC evidence
      05_shorts/<id>/   EDL, ASS captions, framing and QC evidence
      06_copy/<id>/     hook, title, caption, YouTube title, description,
                        LinkedIn, X, alternatives, CTA and metadata
      07_final/
        youtube/       final-youtube.mp4, thumbnail-notes.md, youtube-copy.md
        shorts/01/     clip.mp4, copy.md, metadata.json
        REVIEW-STATUS.md
      logs/            events, usage, approvals and render manifest
      report.md
  templates/           default client, caption presets, graphic source
  tools/               local render dependencies and model cache
  config/studio.yaml
  studio/              Python implementation
  vendor/video-use/    pinned MIT helpers and license
```

Project names become slugs. `latest` means most recently created project, not the
one with the most recently modified file. Use an explicit slug when processing an
older episode. Multiple raw files are separate takes; the plan can combine them.
Audio-only files produce a branded still with the conversation audio and captions.

## Transcription, dependencies and API keys

Default: `faster-whisper` small.en on CPU with int8 and word timestamps. The first
run downloads the model to `tools/cache/whisper`; later transcription is local.
There is no additional API charge. It may omit fillers and mishear proper names.
It has no speaker diarization. Review it before precision editing.

For video-use's preferred verbatim transcription with diarization:

```sh
export ELEVENLABS_API_KEY='your-key'
studio transcribe rui-fu ai-business-podcast --provider elevenlabs
```

Store secrets in your shell environment or your own local secret manager. Do not
commit them or put them in a client profile. The studio does not need an OpenAI,
Anthropic or Gemini key because Codex is the editorial operator. A transcript
cache is reused only when source hash, provider, model, language and audio track
match. Changing these settings selects a separate cache or transcribes again.

Set `audio_track` in `config/studio.yaml` for multi-track camera/OBS recordings.
The same track is used for transcription and output. Track numbering starts at 0.
Set language to null for automatic language detection, or choose a language code.
Use a multilingual model rather than small.en for non-English sources.

FFmpeg's `subtitles` filter is required. The Mac's Homebrew build lacked it during
development, so studio uses the local imageio-ffmpeg binary with libass. ffprobe
still comes from the system. `STUDIO_FFMPEG` can select an explicit FFmpeg build.
Node 22+ is required for HyperFrames. No cloud rendering is used.

For a fresh checkout with Python 3.12+ and system ffprobe:

```sh
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[local,dev]'
cd tools/graphics
npm ci
cd ../..
studio doctor
```

`requirements-lock.txt` records the Python versions used in the verified Mac
environment. The npm lockfile pins graphics dependencies. Private media, model
caches, dependencies and secrets are ignored by Git. ffmpeg binaries and fonts
have their own licenses; the setup does not relicense them.

## What the MVP handles

- Full-source transcript reading with coverage checks, 15-30 candidate proposals
  where the material supports them, topic grouping and editorial ranking.
- Keep-range edits across takes, restrained punch-ins, 30ms cut fades, audio
  normalization, client caption presets and selective animation slots.
- Conservative face-aware crops and explicit manual crop positions. Multiple or
  changing faces fall back to full-picture fit. It does not claim active-speaker
  tracking from audio. Codex can split a shot and specify speaker crops after
  inspecting it. Source-time `crop_keyframes` change the crop at camera switches
  within a continuous audio range, without adding unnecessary audio edits.
- clean, minimal, bold, podcast and creator captions, with optional word emphasis.
- HyperFrames cards and lists, external HyperFrames/Remotion compositions, and
  simple PIL cards. See docs/graphics.md for custom charts and UI graphics.
- Source hashes, resumable ASR/render caches, review records, per-project logs,
  technical QC and human sign-off.

B-roll acquisition, advanced tracking, automatic retake judgment, bespoke charts,
colour decisions and editorial polish remain Codex/operator work, backed by the
saved profile and evidence. The CLI never invents those decisions. This MVP does
not independently learn a client's taste or predict a clip's view count.

## Costs and margin

`report.md` and `logs/cost-summary.json` show processing seconds, API attempts,
known cost, unknown entries, and per-stage usage. Supply your current provider
rates in config/studio.yaml when needed. Unknown prices and unavailable token
counts remain null. Failed API attempts remain recorded. Codex subscription
usage and local electricity are not converted into a guessed per-project cost.

## Validation

```sh
pytest -q
ruff check studio tests
mypy --config-file pyproject.toml
```

The tests include a real FFmpeg render and verify source preservation, caption
timing after edits, review invalidation, path safety, full analysis coverage,
selection replacement and unknown-cost handling. The original Mac also retains
a local docs/development-test.md report with private output paths. That report
and all client data are excluded from the GitHub repository.

Exit codes: 0 success, 1 error, 2 expected review/Codex checkpoint, 130 interrupted.
Rerun after an interruption to reuse completed cached work. Errors never imply
that empty/missing outputs are successful. Read project logs for provider or
render failures.

Upstream licenses, inspected commits and exact reuse are documented in
docs/upstream-review.md. No AutoClip services were installed.
