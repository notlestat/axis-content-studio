from __future__ import annotations

import contextlib
import json
import os
import shutil
import tempfile
from pathlib import Path

from studio.analysis import load_plan, selected, transcript
from studio.captions import build_ass, output_words
from studio.framing import filter_for, find_subject
from studio.graphics import desired_visuals, render_graphic
from studio.ingest import verify_sources
from studio.models import Analysis, Candidate, Cut
from studio.qc import inspect_output, require_technical
from studio.storage import APP, Project, StudioError, digest, now, sha256
from studio.upstream import ffmpeg, helper

SIZES = {"9:16": (1080, 1920), "16:9": (1920, 1080), "1:1": (1080, 1080)}


def size_for(project: Project, target: str):
    return (1920, 1080) if target == "longform" else SIZES[project.profile.shortform.aspect_ratio]


def output_offset(cuts: list[Cut], source: str, timestamp: float):
    offset = 0.0
    for cut in cuts:
        if cut.source == source and cut.start <= timestamp < cut.end:
            return offset + timestamp - cut.start
        offset += cut.end - cut.start
    raise StudioError("Graphic is outside the edited output")


def materialize_audio(project: Project, source: dict, source_path: Path, work: Path, cut: Cut):
    """Audio-only inputs get a branded still, using the same range timebase."""
    from PIL import Image, ImageDraw, ImageFont
    card = work / "audio-card.png"
    image = Image.new("RGB", (1920, 1080), project.profile.brand.primary_colour)
    draw = ImageDraw.Draw(image)
    font: ImageFont.FreeTypeFont | ImageFont.ImageFont
    try:
        font = ImageFont.truetype("/System/Library/Fonts/Supplemental/Arial.ttf", 72)
    except OSError:
        font = ImageFont.load_default(size=72)
    draw.text((150, 340), project.profile.name[:35], font=font, fill=project.profile.brand.secondary_colour)
    draw.text((150, 460), "From the conversation", font=font, fill=project.profile.brand.accent_colour)
    image.save(card)
    video = work / f"audio-{source['id']}-{int(cut.start*1000)}.mp4"
    ffmpeg(["-y", "-loop", "1", "-i", str(card), "-ss", str(cut.start), "-i", str(source_path), "-t", str(cut.end - cut.start), "-map", "0:v:0", "-map", f"1:a:{project.studio.settings().audio_track}", "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac", "-pix_fmt", "yuv420p", "-r", str(project.studio.settings().fps), str(video)])
    return video


def write_copy(project: Project, candidate: Candidate, final_folder: Path):
    if candidate.content_copy is None:
        raise StudioError(f"Copy is missing for {candidate.id}; ask Codex to complete it and reimport analysis")
    copy = candidate.content_copy
    folder = project.file(f"06_copy/{candidate.id}")
    folder.mkdir(parents=True, exist_ok=True)
    files = {"hook.txt": copy.hook, "title.txt": copy.title, "caption.txt": copy.caption, "youtube-title.txt": copy.youtube_title, "description.txt": copy.description, "linkedin.md": copy.linkedin, "x-post.txt": copy.x_post}
    for filename, text in files.items():
        project.text(f"06_copy/{candidate.id}/{filename}", text + "\n")
    metadata = {"candidate": candidate.id, "source": candidate.source, "start_time": candidate.start_time, "end_time": candidate.end_time, "cuts": [c.model_dump() for c in candidate.cuts], "scores": candidate.scores.model_dump(), "copy": copy.model_dump(), "review_status": "needs-human-review"}
    project.write(f"06_copy/{candidate.id}/metadata.json", metadata)
    text = f"# {copy.title}\n\n{copy.hook}\n\n## Caption\n{copy.caption}\n\n## YouTube\n{copy.youtube_title}\n\n{copy.description}\n\n## LinkedIn\n{copy.linkedin}\n\n## X\n{copy.x_post}\n\n## Alternative hooks\n" + "\n".join(f"- {x}" for x in copy.alternative_hooks) + "\n\n## Alternative titles\n" + "\n".join(f"- {x}" for x in copy.alternative_titles) + f"\n\n## CTA\n{copy.cta}\n"
    project.text(str((final_folder / "copy.md").relative_to(project.path)), text)
    project.write(str((final_folder / "metadata.json").relative_to(project.path)), metadata)


def render_one(project: Project, plan: Analysis, target: str, cuts: list[Cut], final: Path, auto: bool):
    from studio.graphics import graphic_key
    entries = verify_sources(project)
    trans = transcript(project)
    size = size_for(project, target)
    graphics = [v for v in desired_visuals(project, plan) if v.target == target]
    graphic_files = [(v, render_graphic(project, v, size)) for v in graphics]
    code_hashes = {name: sha256(APP / name) for name in ["studio/rendering.py", "studio/captions.py", "studio/framing.py", "vendor/video-use/helpers/render.py"]}
    render_key = digest({"inputs": project.input_digest(), "target": target, "cuts": [c.model_dump() for c in cuts], "graphics": [{"key": graphic_key(project, v, size), "sha256": sha256(p)} for v, p in graphic_files], "caption": project.profile.captions.model_dump(), "code": code_hashes})
    old_manifest = project.read("logs/render-manifest.json", {})
    old = old_manifest.get(target)
    if old and old.get("render_key") == render_key and final.exists() and sha256(final) == old["qc"]["sha256"]:
        return {**old, "production_digest": project.review_digest("plan"), "path": str(final.relative_to(project.path))}
    working_base = project.file("04_longform" if target == "longform" else f"05_shorts/{target}")
    working_base.mkdir(parents=True, exist_ok=True)
    final.parent.mkdir(parents=True, exist_ok=True)
    # Work in an ASCII temp directory. This also avoids upstream's concat path quoting
    # issue with apostrophes. Raw sources are only input arguments; never output paths.
    with project.timed("render"), tempfile.TemporaryDirectory(prefix="axis-render-") as temp:
        work = Path(temp)
        render = helper("render")
        segments = []
        decisions = []
        with project.file(f"logs/render-{target}.log").open("a") as log, contextlib.redirect_stdout(log):
            for index, cut in enumerate(cuts):
                source = entries[cut.source]
                source_path = project.file(source["path"])
                center = cut.crop_x
                method = "manual crop" if center is not None else "full picture retained"
                video_stream = next((s for s in source["probe"]["streams"] if s["codec_type"] == "video"), None)
                if video_stream is None:
                    source_path = materialize_audio(project, source, source_path, work, cut)
                    start = 0.0
                else:
                    start = cut.start
                if target != "longform" and center is None and project.profile.shortform.reframe == "auto" and video_stream:
                    center, method = find_subject(source_path, cut)
                if project.profile.shortform.reframe == "manual" and target != "longform" and center is None:
                    raise StudioError(f"Manual framing requested; supply crop_x for {target}")
                grade = filter_for(size, center, cut.punch_in, project.profile.brand.primary_colour, cut.crop_keyframes, cut.start)
                # Reuse video-use extraction: 30ms fades, HDR handling, CFR and codec.
                segment = work / f"segment-{index:03d}.mp4"
                render.extract_segment(source_path, start, cut.end - cut.start, grade, segment, rate=str(project.studio.settings().fps), audio_track=project.studio.settings().audio_track if video_stream else 0)
                segments.append(segment)
                decisions.append({"range": cut.model_dump(), "crop_x": center, "method": method})
            render.concat_segments(segments, work / "base.mp4", work)
            captions = None
            subtitles = None
            if project.profile.captions.enabled and (target != "longform" or project.profile.longform.subtitles):
                subtitles = work / "captions.ass"
                captions = build_ass(cuts, trans, project.profile.captions, size, project.profile.brand.accent_colour, subtitles)
                shutil.copyfile(subtitles, working_base / "captions.ass")
            overlays = []
            for index, (visual, path) in enumerate(graphic_files):
                safe_path = work / f"overlay-{index}.mp4"
                shutil.copyfile(path, safe_path)
                overlays.append({"file": str(safe_path), "start_in_output": output_offset(cuts, visual.source, visual.timestamp), "duration": visual.duration})
            prior_style = render.SUB_FORCE_STYLE
            try:
                # ASS carries full-resolution safe zones and the chosen preset.
                render.SUB_FORCE_STYLE = ""
                render.build_final_composite(work / "base.mp4", overlays, subtitles, work / "composite.mp4", work)
            finally:
                render.SUB_FORCE_STYLE = prior_style
            render.apply_loudnorm_two_pass(work / "composite.mp4", work / "normalized.mp4")
            expected = sum(c.end - c.start for c in cuts)
            qc = inspect_output(work / "normalized.mp4", size, expected, captions)
            project.write(str((working_base / "qc.json").relative_to(project.path)), qc)
            require_technical(qc)
            # Commit only the technically verified render; preserve existing finals until then.
            tmp_final = final.with_name(".next-" + final.name)
            project.file(str(tmp_final.relative_to(project.path)))
            shutil.copyfile(work / "normalized.mp4", tmp_final)
            os.replace(tmp_final, final)
        project.write(str((working_base / "framing.json").relative_to(project.path)), decisions)
        edl = {"version": 1, "sources": {k: str(project.file(v["path"])) for k, v in entries.items()}, "ranges": [c.model_dump() for c in cuts], "overlays": [{"file": str(p), "start_in_output": output_offset(cuts, v.source, v.timestamp), "duration": v.duration} for v, p in graphic_files], "total_duration_s": expected}
        project.write(str((working_base / "edl.json").relative_to(project.path)), edl)
        words = output_words(cuts, trans)
        project.write(str((working_base / "output-transcript.json").relative_to(project.path)), {"words": [{**w, "type": "word"} for w in words]})
        project.text(str((working_base / "qc-checklist.md").relative_to(project.path)), "# Watch and listen before delivery\n\n- Compare first/last words with source.\n- Watch lip sync across every cut.\n- Confirm caption wording, names and numbers.\n- Inspect captions with platform UI safe zones.\n- Watch every graphic at 1x and check that it matches the spoken claim.\n- Check crop and speaker handoffs; face detection does not identify active speakers.\n- Approve QC only after viewing the complete outputs.\n")
    return {"path": str(final.relative_to(project.path)), "production_digest": project.review_digest("plan"), "render_key": render_key, "rendered_at": now(), "experimental": auto, "graphics": [v.id for v in graphics], "qc": qc}


def render_project(project: Project, auto: bool = False):
    plan = load_plan(project)
    clips = selected(project, plan)
    if project.profile.shortform.enabled and not clips:
        raise StudioError("No shorts selected")
    for candidate in clips:
        if candidate.content_copy is None:
            raise StudioError(f"Complete copy for {candidate.id} before rendering")
    if project.profile.longform.enabled and (not plan.youtube_copy or not plan.thumbnail_notes):
        raise StudioError("Longform needs youtube_copy and thumbnail_notes")
    verify_sources(project)
    project.require("transcript", auto)
    project.require("plan", auto)
    project.require("graphics", auto)
    desired_visuals(project, plan)
    previous_manifest = project.read("logs/render-manifest.json", {})
    manifest = dict(previous_manifest)
    if project.profile.longform.enabled:
        target = project.file("07_final/youtube/final-youtube.mp4")
        manifest["longform"] = render_one(project, plan, "longform", plan.longform, target, auto)
        project.write("logs/render-manifest.json", manifest)
        project.text("07_final/youtube/youtube-copy.md", plan.youtube_copy + "\n")
        project.text("07_final/youtube/thumbnail-notes.md", plan.thumbnail_notes + "\n")
    for index, candidate in enumerate(clips, start=1):
        folder = project.file(f"07_final/shorts/{index:02d}")
        folder.mkdir(parents=True, exist_ok=True)
        manifest[candidate.id] = render_one(project, plan, candidate.id, candidate.cuts, folder / "clip.mp4", auto)
        write_copy(project, candidate, folder)
        project.write("logs/render-manifest.json", manifest)
    wanted = {c.id for c in clips} | ({"longform"} if project.profile.longform.enabled else set())
    manifest = {key: value for key, value in manifest.items() if key in wanted}
    project.write("logs/render-manifest.json", manifest)
    # Retire outputs that are no longer selected without deleting their media.
    shorts_dir = project.file("07_final/shorts")
    if shorts_dir.exists():
        for folder in shorts_dir.iterdir():
            if folder.is_dir() and folder.name.isdigit() and int(folder.name) > len(clips):
                retired = project.file("05_shorts/retired")
                retired.mkdir(parents=True, exist_ok=True)
                import time
                shutil.move(str(folder), str(retired / f"{folder.name}-{time.time_ns()}"))
    if not project.profile.longform.enabled and project.file("07_final/youtube").exists():
        import time
        shutil.move(str(project.file("07_final/youtube")), str(project.file(f"04_longform/retired-{time.time_ns()}")))
    project.text("07_final/REVIEW-STATUS.md", "# Experimental outputs\n\nNot approved for delivery. Watch all outputs and run studio approve ... qc.\n" if auto else "# Awaiting final human QC\n\nTechnical checks passed. Watch and listen before approving delivery.\n")
    return manifest


def inspect_boundaries(project: Project, target: str):
    manifest = project.read("logs/render-manifest.json", {})
    if target not in manifest:
        raise StudioError("Unknown rendered target")
    work = project.file("04_longform" if target == "longform" else f"05_shorts/{target}")
    edl = json.loads((work / "edl.json").read_text())
    total = edl["total_duration_s"]
    times = [0, total / 3, total * 2 / 3, max(0, total - 2)]
    offset = 0
    for cut in edl["ranges"][:-1]:
        offset += cut["end"] - cut["start"]
        times.append(offset)
    helper_path = Path(helper("timeline_view").__file__)
    import subprocess
    import sys
    for index, point in enumerate(times):
        destination = work / "verify" / f"boundary-{index:03d}.png"
        destination.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run([sys.executable, str(helper_path), str(project.file(manifest[target]["path"])), str(max(0, point - 1.5)), str(min(total - .06, point + 1.5)), "--n-frames", "6", "--transcript", str(work / "output-transcript.json"), "-o", str(destination)], check=True)
    return work / "verify"
