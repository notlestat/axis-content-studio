# Axis content studio

A Codex skill and local Python CLI for a one-person content editing business.
Give Codex footage, a client name and an editing brief. It uses saved preferences
to prepare a transcript, edit plan, shorts, graphics and supporting copy. You
review the choices and final videos before delivery.

```text
skills/axis-content-studio/   Installable Codex instructions and launcher
content-studio/              Working CLI, templates, tests and media adapters
tools/install-skill.py       Local skill installer
AGENTS.md                   Instructions for this checkout
```

The skill operates the Python application. Client media and projects stay local
and are excluded from Git.

## Install

Verified on macOS with Python 3.12, Node 22 or newer, and system `ffprobe`.
Install those prerequisites first. Python dependencies include a subtitle-capable
FFmpeg fallback.

```sh
git clone https://github.com/notlestat/axis-content-studio.git
cd axis-content-studio
python3 -m venv content-studio/.venv
content-studio/.venv/bin/python -m pip install -e './content-studio[local,dev]'
npm ci --prefix content-studio/tools/graphics
content-studio/.venv/bin/studio doctor
python3 tools/install-skill.py
```

The installer copies the skill into `$CODEX_HOME/skills/axis-content-studio`, or
`~/.codex/skills/axis-content-studio` when CODEX_HOME is unset. It saves a local
binding to this checkout. Keep the checkout in place. To move it, set
`AXIS_STUDIO_APP` to its new `content-studio` directory or update the installed
skill's `config.local.json`. The installer refuses to overwrite an existing skill;
move an existing installation aside before reinstalling.

A skill installed separately from GitHub still needs the complete application
and Python environment. Point `AXIS_STUDIO_APP` at that application's directory.

## Use through Codex

```text
Use $axis-content-studio. This is Rui's podcast at /path/to/episode.mp4.
Make five 30-60 second business shorts with clean captions and restrained
graphics. No longform edit.
```

For later projects, say "Process Rui's latest project." The skill can activate
automatically for this workflow. It reads client preferences, safely ingests the
source and pauses at review checkpoints. Explicit experiments can use `--auto`;
that flag never records human QC.

See [the operating README](content-studio/README.md) for client setup, manual
commands, review controls and output paths. Read
[graphics guidance](content-studio/docs/graphics.md) for custom animation slots.

Local Whisper works without an API key. ElevenLabs Scribe is optional and reads
`ELEVENLABS_API_KEY` from the environment. Editorial analysis runs through Codex.
Unknown token counts and costs remain unknown in project reports.

## Verify

```sh
cd content-studio
.venv/bin/pytest -q
.venv/bin/ruff check studio tests ../skills ../tools
.venv/bin/mypy --config-file pyproject.toml
```

The original private development run used a 44-minute business podcast, generated
18 candidates, rendered a representative YouTube section and three shorts, and
included a HyperFrames insert. Its footage, transcript, copy and exports are not
distributed here. Technical checks do not replace watching and listening before
delivery.

## Upstream code

Selected MIT-licensed video-use helpers handle transcription, editing, compositing
and QC. AutoClip informed the analysis workflow; its runtime was not copied.
Licenses and exact reuse are documented in
[upstream-review.md](content-studio/docs/upstream-review.md).
