from __future__ import annotations

import json
import math
import subprocess
from pathlib import Path

from studio.storage import StudioError, sha256
from studio.upstream import configure_media, probe


def inspect_output(path: Path, size: tuple[int, int], expected_duration: float, captions: dict | None):
    configure_media()
    data = probe(path)
    streams = data["streams"]
    video = next((s for s in streams if s["codec_type"] == "video"), None)
    audio = next((s for s in streams if s["codec_type"] == "audio"), None)
    failures = []
    if video is None or (video.get("width"), video.get("height")) != size:
        failures.append("Incorrect video resolution")
    if audio is None:
        failures.append("Audio stream missing")
    duration = float(data["format"]["duration"])
    if abs(duration - expected_duration) > max(.2, expected_duration * .001):
        failures.append(f"Duration differs from edit plan: {duration:.3f} vs {expected_duration:.3f}")
    if video and audio:
        start_delta = abs(float(video.get("start_time", 0)) - float(audio.get("start_time", 0)))
        end_delta = abs(float(video.get("duration", duration)) - float(audio.get("duration", duration)))
        if start_delta > .1 or end_delta > .15:
            failures.append(f"Audio/video stream timing difference: start {start_delta:.3f}s, duration {end_delta:.3f}s")
    decode = subprocess.run(["ffmpeg", "-v", "error", "-nostdin", "-i", str(path), "-map", "0:v:0", "-map", "0:a:0", "-f", "null", "-"], capture_output=True, text=True)
    if decode.returncode or decode.stderr.strip():
        failures.append("Decode errors: " + decode.stderr[-600:])
    if captions:
        for cue in captions["cues"]:
            if cue["end"] > duration + .05 or cue["start"] < 0 or cue["lines"] > captions["max_lines"]:
                failures.append("Caption timing or line count failed")
                break
    # Signal diagnostics flag intervals for review; black screens/pauses may be intentional.
    signal = subprocess.run(["ffmpeg", "-hide_banner", "-nostdin", "-i", str(path), "-vf", "blackdetect=d=0.3:pix_th=0.10", "-af", "loudnorm=I=-14:TP=-1:LRA=11:print_format=json", "-f", "null", "-"], capture_output=True, text=True)
    warnings = [line.strip() for line in signal.stderr.splitlines() if "black_start:" in line]
    loudness = None
    begin, end = signal.stderr.rfind("{"), signal.stderr.rfind("}")
    if begin >= 0 and end > begin:
        measured = json.loads(signal.stderr[begin:end + 1])
        loudness = {key: float(measured[key]) if math.isfinite(float(measured[key])) else None for key in ["input_i", "input_tp", "input_lra"]}
        if loudness["input_i"] is None:
            failures.append("Output audio is silent")
        elif abs(loudness["input_i"] + 14) > 2:
            warnings.append(f"Integrated loudness is {loudness['input_i']} LUFS; target is -14")
        if loudness["input_tp"] is not None and loudness["input_tp"] > 0:
            failures.append("Audio true peak exceeds 0 dBTP")
    else:
        failures.append("Audio measurement failed")
    return {"technical_pass": not failures, "failures": failures, "warnings": warnings, "duration": duration, "expected_duration": expected_duration, "resolution": size, "loudness": loudness, "sha256": sha256(path), "decode": "passed" if not decode.returncode and not decode.stderr.strip() else "failed", "human_checks": {"lip_sync": "needs watching", "word_edges": "needs listening", "caption_accuracy": "needs transcript comparison", "safe_zones": "layout enforced; inspect rendered text", "graphics": "needs watching", "editorial_quality": "needs watching"}, "publish_ready": False}


def require_technical(qc: dict):
    if not qc["technical_pass"]:
        raise StudioError("QC failed: " + "; ".join(qc["failures"]))
