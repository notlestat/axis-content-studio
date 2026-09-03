# Editorial analysis and delivery

Use commands through `scripts/run_studio.py` or the located application's environment.
Replace identifiers with those returned by the CLI.

## Transcript

`process <client> [project]` inventories sources, transcribes when needed and stops
at the next review gate. Read `02_transcript/transcript.md` and its JSON. Check
names, numbers and cut edges against source audio. Local ASR may omit fillers and
has no diarization. Paid Scribe usage needs the relevant authorization and key.

After correcting JSON, rebuild the readable form with `transcribe <client>
<project> --import-json <transcript.json>`. Show `review <client> <project>
transcript`. Record `approve <client> <project> transcript --note '<review notes>'`
only after the actual decision.

## Complete-source analysis

1. Run `analyze prepare <client> <project>`.
2. Read `03_analysis/brief.md`, `analysis.schema.json`, `coverage-required.json`
   and every listed chunk. Use the actual schema rather than remembered fields.
3. Author `03_analysis/analysis-proposal.json` with the current input digest,
   coverage of every source, 15-30 grounded candidates where supported, distinct
   topic groups, editorial scores, natural keep ranges and copy. Explain a
   shortage when the source cannot support 15 distinct candidates.
4. For enabled longform, include keep ranges, YouTube copy and thumbnail notes.
   Use `representative-section` only for an explicitly requested sample.
5. Inspect source frames at starts, ends and camera switches. `crop_x` is a
   normalized horizontal subject position; `crop_keyframes` use source seconds.
   Automatic framing fits the whole picture when it cannot isolate a stable
   subject. It does not identify active speakers from audio.
6. Propose selective visuals with source timestamps, spoken context, concept,
   engine, priority and target clip. Each must fit entirely inside a kept range.
   Avoid duplicate ideas and invented statistics, quotations or assets.
7. Run `analyze import <client> <project> <analysis-proposal.json>`. Import checks
   coverage and timing, snaps word boundaries and recalculates default selections.
   Reapply requested selections after a new import.

`--auto` does not call a hidden LLM. Codex still reads the transcript and authors
analysis when the application exports its brief.

## Review and render

```sh
studio review <client> <project> plan
studio clips reject <client> <project> <candidate-id>
studio clips approve <client> <project> <candidate-id>
studio clips replace <client> <project> <old-id> <new-id>
studio review <client> <project> graphics
studio graphics reject <client> <project> <visual-id>
```

Show actual selected clips, source times, edits and visuals. Record `plan` and
`graphics` approval after the corresponding decisions. Run `render <client>
<project>`. Changes to inputs or selections invalidate approval. Do not bypass a
stale-analysis error.

For custom diagrams, charts or UI graphics, read the application's
`docs/graphics.md`. Build a checked HyperFrames or Remotion composition and attach
its MP4 through `graphics attach`. The stock renderer handles type and lists.
Never label a static PIL card as a HyperFrames animation.

## QC and handoff

Run `qc <client> <project>` and `qc <client> <project> --inspect <target>`, where
target is `longform` or a rendered candidate ID. Inspect filmstrips, crop switches,
caption safe areas and graphic frames. Watch and listen to complete outputs for
sync, audible word edges and caption accuracy. If available tools cannot provide
that perceptual review, state it and leave human QC pending. Technical checks
alone cannot establish those properties.

After the operator completes final review, record `approve ... qc` with their
notes. Run `report <client> <project>` and return actual video and copy paths,
decisions, processing time, known costs, unknown usage and unresolved issues.
Videos live in `07_final`; copy source files live in `06_copy`. No upload or
publication is part of normal processing.
