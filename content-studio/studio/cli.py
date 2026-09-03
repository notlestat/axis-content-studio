from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

from pydantic import ValidationError

from studio import __version__
from studio.analysis import change_selection, import_analysis, load_plan, prepare, review_text
from studio.graphics import attach, desired_visuals, render_graphic
from studio.ingest import inventory, register, verify_sources, youtube
from studio.rendering import inspect_boundaries, render_project, size_for
from studio.reporting import report
from studio.storage import APP, ReviewRequired, Studio, StudioError, sha256
from studio.transcription import import_transcript, transcribe
from studio.upstream import configure_media


def project_args(parser):
    parser.add_argument("client")
    parser.add_argument("project", nargs="?", default="latest")


def parser():
    ap = argparse.ArgumentParser(prog="studio", description="Local content production. Review before delivery.")
    ap.add_argument("--root", type=Path, help="Alternate client/config root")
    ap.add_argument("--version", action="version", version=__version__)
    sub = ap.add_subparsers(dest="command", required=True)
    sub.add_parser("doctor", help="Check local dependencies, optional keys, and renderer capabilities")
    client = sub.add_parser("client").add_subparsers(dest="action", required=True)
    client.add_parser("create").add_argument("name")
    client.add_parser("list")
    client.add_parser("validate").add_argument("client")
    project = sub.add_parser("project").add_subparsers(dest="action", required=True)
    create = project.add_parser("create")
    create.add_argument("client")
    create.add_argument("title")
    create.add_argument("--private-test", action="store_true")
    project_args(sub.add_parser("status"))
    ingest = sub.add_parser("ingest")
    project_args(ingest)
    ingest.add_argument("--file", type=Path)
    ingest.add_argument("--youtube")
    process = sub.add_parser("process", help="Resume latest project and stop at the next review gate")
    project_args(process)
    process.add_argument("--auto", action="store_true")
    trans = sub.add_parser("transcribe")
    project_args(trans)
    trans.add_argument("--provider", choices=["local", "elevenlabs"])
    trans.add_argument("--model")
    trans.add_argument("--import-json", type=Path)
    analysis = sub.add_parser("analyze").add_subparsers(dest="action", required=True)
    project_args(analysis.add_parser("prepare"))
    imp = analysis.add_parser("import")
    imp.add_argument("client")
    imp.add_argument("project")
    imp.add_argument("file", type=Path)
    for name in ["review", "approve"]:
        cmd = sub.add_parser(name)
        cmd.add_argument("client")
        cmd.add_argument("project")
        cmd.add_argument("stage", choices=["transcript", "plan", "graphics", "qc"])
        if name == "approve":
            cmd.add_argument("--note", required=True, help="What you checked; records human review")
    clips = sub.add_parser("clips")
    clips.add_argument("action", choices=["approve", "reject", "replace"])
    clips.add_argument("client")
    clips.add_argument("project")
    clips.add_argument("ids", nargs="+")
    graphics = sub.add_parser("graphics")
    graphics.add_argument("action", choices=["approve", "reject", "build", "attach"])
    graphics.add_argument("client")
    graphics.add_argument("project")
    graphics.add_argument("ids", nargs="*")
    graphics.add_argument("--file", type=Path)
    graphics.add_argument("--auto", action="store_true")
    render = sub.add_parser("render")
    project_args(render)
    render.add_argument("--auto", action="store_true")
    qc = sub.add_parser("qc")
    project_args(qc)
    qc.add_argument("--inspect", help="Generate video-use filmstrips for one rendered target")
    project_args(sub.add_parser("report"))
    return ap


def doctor(studio: Studio):
    configure_media()
    result = subprocess.run(["ffmpeg", "-filters"], capture_output=True, text=True, check=True)
    checks = {"root": str(studio.root), "python": sys.version.split()[0], "ffmpeg": shutil.which("ffmpeg"), "ffprobe": shutil.which("ffprobe"), "subtitles": " subtitles " in result.stdout, "yt_dlp": __import__("yt_dlp.version", fromlist=["__version__"]).__version__, "node": shutil.which("node"), "hyperframes": (APP / "tools/graphics/node_modules/.bin/hyperframes").exists(), "elevenlabs_key_present": bool(os.environ.get("ELEVENLABS_API_KEY")), "analysis": "Codex session reads brief.md and imports validated JSON; no separate LLM key needed"}
    print(json.dumps(checks, indent=2))
    if not checks["subtitles"]:
        raise StudioError("FFmpeg subtitles filter unavailable")


def approve(project, stage, note):
    if not note.strip():
        raise StudioError("Review note cannot be blank")
    verify_sources(project)
    if stage == "transcript":
        from studio.analysis import transcript
        transcript(project)
    elif stage == "qc":
        manifest = project.read("logs/render-manifest.json", {})
        if not manifest:
            raise StudioError("No renders to approve")
        plan = load_plan(project)
        from studio.analysis import selected
        wanted = {c.id for c in selected(project, plan)} | ({"longform"} if project.profile.longform.enabled else set())
        if set(manifest) != wanted:
            raise StudioError("The selected outputs have not all been rendered. Run studio render again.")
        for item in manifest.values():
            if item.get("production_digest") != project.review_digest("plan"):
                raise StudioError("The plan or selection changed after rendering. Run studio render again.")
            if not item["qc"]["technical_pass"] or sha256(project.file(item["path"])) != item["qc"]["sha256"]:
                raise StudioError("Renders changed or technical QC failed")
        for previous in ["transcript", "plan", "graphics"]:
            project.require(previous)
    else:
        load_plan(project)
        if stage == "graphics":
            desired_visuals(project, load_plan(project))
    project.approve(stage, note)
    if stage == "qc":
        project.text("07_final/REVIEW-STATUS.md", f"# Human QC approved\n\n{note}\n\nSee logs/approval-qc.json for the exact reviewed digest.\n")


def dispatch(args, studio):
    if args.command == "doctor":
        return doctor(studio)
    if args.command == "client":
        if args.action == "create":
            print(studio.create_client(args.name))
        elif args.action == "validate":
            print(json.dumps(studio.client(args.client).model_dump(), indent=2))
        else:
            parent = studio.root / "clients"
            for file in sorted(parent.glob("*/client.yaml")):
                print(f"{file.parent.name}\t{studio.client(file.parent.name).name}")
        return
    if args.command == "project":
        print(studio.create_project(args.client, args.title, args.private_test).path)
        return
    project = studio.project(args.client, args.project)
    if args.command == "status":
        manifest = project.read("logs/render-manifest.json", {})
        print(json.dumps({"project": str(project.path), "sources": len(project.read("sources.json", [])), "transcript": project.file("02_transcript/transcript.json").exists(), "analysis": project.file("03_analysis/analysis.json").exists(), "reviews": {s: project.approved(s) for s in ["transcript", "plan", "graphics", "qc"]}, "rendered": list(manifest)}, indent=2))
        return
    with project.lock():
        if args.command == "ingest":
            if args.file and args.youtube:
                raise StudioError("Use either --file or --youtube")
            if args.file:
                print(register(project, args.file)["id"])
            elif args.youtube:
                with project.timed("download"):
                    print(youtube(project, args.youtube)["id"])
            else:
                print(json.dumps(inventory(project), indent=2))
        elif args.command == "transcribe":
            inventory(project)
            if args.import_json:
                import_transcript(project, args.import_json)
            else:
                transcribe(project, args.provider, args.model)
            print(project.file("02_transcript/transcript.md"))
        elif args.command == "analyze":
            if args.action == "prepare":
                print(prepare(project))
            else:
                import_analysis(project, args.file)
                print(review_text(project, "plan"))
        elif args.command == "review":
            if args.stage == "qc":
                print(report(project).read_text())
            else:
                print(review_text(project, args.stage))
        elif args.command == "approve":
            approve(project, args.stage, args.note)
            print(f"Approved {args.stage} for the current project state")
        elif args.command == "clips":
            change_selection(project, "clips", args.action, args.ids)
        elif args.command == "graphics":
            if args.action in {"approve", "reject"}:
                change_selection(project, "graphics", args.action, args.ids)
            else:
                plan = load_plan(project)
                project.require("plan", args.auto)
                project.require("graphics", args.auto)
                visuals = desired_visuals(project, plan)
                if args.ids:
                    if not set(args.ids) <= {v.id for v in visuals}:
                        raise StudioError("Requested graphic is not selected")
                    visuals = [v for v in visuals if v.id in args.ids]
                if args.action == "attach":
                    if not args.file or len(visuals) != 1:
                        raise StudioError("Attach needs one graphic ID and --file")
                    attach(project, visuals[0], size_for(project, visuals[0].target), args.file)
                else:
                    for visual in visuals:
                        print(render_graphic(project, visual, size_for(project, visual.target)))
        elif args.command == "render":
            render_project(project, args.auto)
            print(report(project))
        elif args.command == "qc":
            if args.inspect:
                print(inspect_boundaries(project, args.inspect))
            else:
                print(json.dumps(project.read("logs/render-manifest.json", {}), indent=2))
        elif args.command == "report":
            print(report(project))
        elif args.command == "process":
            inventory(project)
            transcribe(project)
            project.require("transcript", args.auto)
            if not project.file("03_analysis/analysis.json").exists():
                print(prepare(project))
                raise ReviewRequired("Codex: read the full brief and all coverage chunks, author analysis-proposal.json, then studio analyze import. --auto does not invent an analysis.")
            load_plan(project)
            project.require("plan", args.auto)
            project.require("graphics", args.auto)
            render_project(project, args.auto)
            print(report(project))


def main(argv=None):
    args = parser().parse_args(argv)
    try:
        dispatch(args, Studio(args.root))
    except ReviewRequired as exc:
        print(f"REVIEW REQUIRED: {exc}", file=sys.stderr)
        return 2
    except (StudioError, ValidationError, FileNotFoundError, json.JSONDecodeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    except subprocess.CalledProcessError as exc:
        message = exc.stderr or "See the project log for details"
        if isinstance(message, bytes):
            message = message.decode(errors="replace")
        print(f"Media command failed: {message[-2000:]}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("Interrupted. Original footage is untouched; rerun to resume cached work.", file=sys.stderr)
        return 130
    return 0


if __name__ == "__main__":
    sys.exit(main())
