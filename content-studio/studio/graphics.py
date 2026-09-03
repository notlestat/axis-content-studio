from __future__ import annotations

import html
import json
import os
import re
import shutil
import subprocess
import textwrap
from pathlib import Path

from studio.analysis import graphic_budget
from studio.models import Analysis, Visual
from studio.storage import APP, Project, StudioError, atomic_text, contained, digest, sha256
from studio.upstream import ffmpeg, probe


def desired_visuals(project: Project, plan: Analysis):
    selection = project.read("03_analysis/selection.json")
    by_id = {v.id: v for v in plan.visuals}
    if not set(selection["graphics"]) <= set(by_id):
        raise StudioError("Unknown graphic selection")
    visuals = [by_id[v] for v in selection["graphics"]]
    for target in {v.target for v in visuals}:
        if len([v for v in visuals if v.target == target]) > graphic_budget(project, plan, target):
            raise StudioError(f"Too many graphics for {target}; adjust client frequency or reject some graphics")
        if target != "longform" and target not in selection["clips"]:
            raise StudioError("Graphic targets an unselected clip")
        if target == "longform" and (not project.profile.longform.enabled or not project.profile.longform.motion_graphics):
            raise StudioError("Longform graphics are disabled in client.yaml")
    return visuals


def brand_logo(project: Project):
    value = project.profile.brand.logo
    if not value:
        return None
    base = project.studio.client_path(project.client_slug)
    path = contained(base / "brand", base / value)
    if not path.is_file():
        raise StudioError(f"Brand logo is missing: {path}")
    from PIL import Image
    try:
        with Image.open(path) as logo:
            logo.verify()
    except OSError as exc:
        raise StudioError("Use a valid PNG, JPEG or WebP brand logo") from exc
    return path


def graphic_key(project: Project, visual: Visual, size):
    logo = brand_logo(project)
    return digest({"visual": visual.model_dump(), "brand": project.profile.brand.model_dump(), "logo_sha256": sha256(logo) if logo else None, "style": project.profile.graphics.model_dump(), "size": size, "renderer": sha256(Path(__file__))})


def slot_path(project: Project, visual: Visual):
    return project.file(f"03_analysis/animations/slot-{visual.id}")


def render_graphic(project: Project, visual: Visual, size: tuple[int, int]):
    slot = slot_path(project, visual)
    slot.mkdir(parents=True, exist_ok=True)
    key = graphic_key(project, visual, size)
    info = project.read(str((slot / "asset.json").relative_to(project.path)), {})
    output = slot / "render.mp4"
    if info.get("key") == key and output.exists() and info.get("sha256") == sha256(output):
        return output
    engine = visual.recommended_engine
    if project.profile.graphics.engine != "auto" and engine != project.profile.graphics.engine:
        raise StudioError(f"Graphic {visual.id} requests {engine}, but client uses {project.profile.graphics.engine}. Update the proposal or client profile.")
    if engine == "remotion":
        raise StudioError(f"Render this React composition with Remotion into {slot}/external.mp4, then run studio graphics attach. See docs/graphics.md.")
    with project.timed("graphics"):
        if engine == "hyperframes":
            hyperframes(project, visual, size, slot)
        elif engine == "pil":
            pil_card(project, visual, size, output)
    validate_asset(output, visual.duration, size)
    project.write(str((slot / "asset.json").relative_to(project.path)), {"key": key, "sha256": sha256(output), "engine": engine, "duration": visual.duration, "dimensions": size})
    project.ledger("graphics", "local", engine, 0, api_calls=0)
    return output


def validate_asset(path: Path, duration: float, size):
    data = probe(path)
    video = next((s for s in data["streams"] if s["codec_type"] == "video"), None)
    if video is None or (video["width"], video["height"]) != tuple(size):
        raise StudioError("Graphic resolution does not match the output")
    if abs(float(data["format"]["duration"]) - duration) > .12:
        raise StudioError("Graphic duration does not match its opportunity")


def attach(project: Project, visual: Visual, size, path: Path):
    validate_asset(path, visual.duration, size)
    slot = slot_path(project, visual)
    slot.mkdir(parents=True, exist_ok=True)
    destination = project.file(str((slot / "render.mp4").relative_to(project.path)))
    if path.resolve() != destination.resolve():
        shutil.copyfile(path, destination)
    project.write(str((slot / "asset.json").relative_to(project.path)), {"key": graphic_key(project, visual, size), "sha256": sha256(destination), "engine": visual.recommended_engine, "duration": visual.duration, "dimensions": size})


def hyperframes(project: Project, visual: Visual, size, slot: Path):
    tool_dir = APP / "tools/graphics"
    binary = tool_dir / "node_modules/.bin/hyperframes"
    if not binary.exists():
        raise StudioError("Install graphics dependencies: cd tools/graphics && npm ci")
    env = {**os.environ, "HYPERFRAMES_SKIP_SKILLS": "1", "DO_NOT_TRACK": "1"}
    with (slot / "commands.log").open("a") as log:
        if not (slot / "hyperframes.json").exists():
            # init requires an empty directory. Use a clean child and keep logs outside it.
            scaffold = slot / "composition"
            result = subprocess.run([str(binary), "init", str(scaffold), "--example", "blank", "--non-interactive", "--resolution", "portrait" if size[1] > size[0] else "landscape"], stdout=log, stderr=log, env=env)
            if result.returncode:
                raise StudioError(f"HyperFrames init failed. See {slot / 'commands.log'}")
            shutil.copyfile(scaffold / "hyperframes.json", slot / "hyperframes.json")
        gsap = tool_dir / "node_modules/gsap/dist/gsap.min.js"
        shutil.copyfile(gsap, slot / "gsap.min.js")
        width, height = size
        brand = project.profile.brand
        font_family = json.dumps(brand.fonts[0]).replace("<", "\\3c ")
        vertical = height > width
        hsize = 78 if vertical else 86
        lsize = 54 if vertical else 56
        body = "".join(f'<li class="item">{html.escape(line)}</li>' for line in visual.lines)
        text = f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><title>{html.escape(visual.headline)}</title><script src="gsap.min.js"></script>
<style>*{{box-sizing:border-box}}body{{margin:0;background:{brand.primary_colour};color:{brand.secondary_colour};font-family:{html.escape(json.dumps(brand.fonts[0]))},Arial,sans-serif}}#root{{width:{width}px;height:{height}px;position:relative;overflow:hidden}}.clip{{position:absolute;inset:0}}.content{{position:absolute;left:{int(width*.10)}px;right:{int(width*.15)}px;top:{int(height*(.19 if vertical else .20))}px}}.tag{{font-size:24px;color:{brand.accent_colour};letter-spacing:4px;text-transform:uppercase;margin:0 0 34px}}h1{{font-size:{hsize}px;line-height:1.10;letter-spacing:-2px;margin:0 0 40px;overflow-wrap:break-word}}ul{{list-style:none;padding:0;margin:0;display:grid;gap:24px}}li{{font-size:{lsize}px;line-height:1.22;margin:0;padding-left:28px;border-left:5px solid {brand.accent_colour};overflow-wrap:break-word}}.rule{{width:130px;height:7px;margin:0 0 45px;background:{brand.accent_colour}}}</style></head><body>
<div id="root" data-composition-id="main" data-width="{width}" data-height="{height}" data-duration="{visual.duration}"><section class="clip" data-start="0" data-duration="{visual.duration}"><div class="content"><p class="tag">{html.escape(visual.type.replace('_',' '))}</p><div class="rule"></div><h1 id="headline">{html.escape(visual.headline)}</h1><ul>{body}</ul></div></section></div>
<script>const tl=gsap.timeline({{paused:true}});tl.fromTo('.rule',{{scaleX:0,transformOrigin:'left center'}},{{scaleX:1,duration:.55,ease:'power3.out'}},.08);tl.fromTo('#headline',{{y:24,opacity:0}},{{y:0,opacity:1,duration:.6,ease:'power3.out'}},.15);tl.fromTo('.item',{{y:20,opacity:0}},{{y:0,opacity:1,duration:.55,stagger:.6,ease:'power3.out'}},.85);window.__timelines['main']=tl;</script></body></html>"""
        component = (APP / "templates/graphic-slot/compositions/components/soft-blur-in.html").read_text()
        style_match = re.search(r"<style[\s\S]*?</style>", component)
        script_match = re.search(r"<script>[\s\S]*?</script>", component)
        if style_match is None or script_match is None:
            raise StudioError("The installed soft-blur-in template is incomplete")
        component_style = style_match.group(0)
        component_script = script_match.group(0)
        text = text.replace(html.escape(json.dumps(brand.fonts[0])), font_family)
        text = text.replace("</head>", f"<style>@font-face{{font-family:{font_family};src:local({font_family})}}</style>" + component_style + "</head>")
        text = text.replace('<section class="clip"', '<section id="graphic-scene" class="clip"')
        text = text.replace("window.__timelines['main']=tl", "window.__timelines=window.__timelines||{};window.__timelines['main']=tl")
        logo = brand_logo(project)
        if logo:
            from PIL import Image
            with Image.open(logo) as image:
                image.convert("RGBA").save(slot / "brand-logo.png")
            text = text.replace('<div class="content">', f'<img id="brand-logo" src="brand-logo.png" alt="" style="position:absolute;left:10%;top:6%;width:{int(width*.18)}px;height:{int(height*.06)}px;object-fit:contain;object-position:left"><div class="content">')
        text = text.replace('class="item"', 'class="item hf-soft-blur-in"').replace('id="headline"', 'id="headline" class="hf-soft-blur-in"')
        text = text.replace("<script>const tl", component_script + "<script>const tl")
        text = text.replace("tl.fromTo('#headline',{y:24,opacity:0},{y:0,opacity:1,duration:.6,ease:'power3.out'},.15)", "tl.to('#headline',{y:0,opacity:1,filter:'blur(0px)',duration:.6,ease:'power3.out'},.15)")
        text = text.replace("tl.fromTo('.item',{y:20,opacity:0},{y:0,opacity:1,duration:.55,stagger:.6,ease:'power3.out'},.85)", "tl.to('.item',{y:0,opacity:1,filter:'blur(0px)',duration:.55,stagger:.6,ease:'power3.out'},.85)")
        atomic_text(slot / "index.html", text)
        atomic_text(slot / "BRIEF.md", f"---\nworkflow: general-video\nflow: automation\nstoryboard: no\n---\n# Approved studio slot\n{visual.visual_concept}\n\nDuration: {visual.duration}s. Use the client brand. The containing project review gates control approval.\n")
        for args in [["check", str(slot), "--json"], ["render", str(slot), "--fps", str(project.studio.settings().fps), "--output", str(slot / "render.mp4")]]:
            result = subprocess.run([str(binary), *args], stdout=log, stderr=log, env=env)
            if result.returncode:
                raise StudioError(f"HyperFrames {args[0]} failed; inspect {slot / 'commands.log'}")


def pil_card(project: Project, visual: Visual, size, output: Path):
    """Small, deterministic graphic using video-use's supported PIL slot convention."""
    from PIL import Image, ImageDraw, ImageFont
    width, height = size
    font_path = "/System/Library/Fonts/Supplemental/Arial.ttf"
    try:
        title_font = ImageFont.truetype(font_path, 76 if height > width else 86)
        body_font = ImageFont.truetype(font_path, 50)
    except OSError:
        title_font = ImageFont.truetype("DejaVuSans.ttf", 72)
        body_font = ImageFont.truetype("DejaVuSans.ttf", 48)
    brand = project.profile.brand
    image = Image.new("RGB", size, brand.primary_colour)
    logo_path = brand_logo(project)
    if logo_path:
        with Image.open(logo_path) as source_logo:
            logo_image = source_logo.convert("RGBA")
            logo_image.thumbnail((int(width * .18), int(height * .06)))
            image.paste(logo_image, (int(width * .1), int(height * .06)), logo_image)
    draw = ImageDraw.Draw(image)
    x, y = int(width * .1), int(height * .2)
    draw.rectangle((x, y, x + 130, y + 6), fill=brand.accent_colour)
    y += 70
    for line in textwrap.wrap(visual.headline, 18 if height > width else 34):
        draw.text((x, y), line, font=title_font, fill=brand.secondary_colour)
        y += 92
    y += 35
    for line in visual.lines:
        for row in textwrap.wrap(line, 25 if height > width else 50):
            draw.text((x, y), row, font=body_font, fill=brand.accent_colour)
            y += 64
        y += 20
    if y > height * .68 and height > width:
        raise StudioError("Graphic text would collide with the caption safe zone")
    still = output.with_suffix(".png")
    image.save(still)
    ffmpeg(["-y", "-loop", "1", "-i", str(still), "-t", str(visual.duration), "-vf", "fade=t=in:st=0:d=0.25", "-r", str(project.studio.settings().fps), "-c:v", "libx264", "-pix_fmt", "yuv420p", "-an", str(output)])
