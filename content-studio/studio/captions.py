from __future__ import annotations

import re
import textwrap
from pathlib import Path

from studio.models import Captions, Cut, Transcript
from studio.storage import StudioError, atomic_text

PRESETS = {
    "clean": {"words": 5, "font_size": 58, "bold": 0, "outline": 3},
    "minimal": {"words": 7, "font_size": 48, "bold": 0, "outline": 2},
    "bold": {"words": 3, "font_size": 66, "bold": 1, "outline": 4},
    "podcast": {"words": 6, "font_size": 54, "bold": 0, "outline": 3},
    "creator": {"words": 3, "font_size": 62, "bold": 1, "outline": 3},
}


def output_words(cuts: list[Cut], trans: Transcript):
    by_source = {s.source: s for s in trans.sources}
    result = []
    offset = 0.0
    for cut in cuts:
        cut_words: list[dict] = []
        for word in by_source[cut.source].words:
            if word.type == "word" and word.start >= cut.start - .001 and word.end <= cut.end + .001:
                item: dict = {"text": word.text, "start": round(word.start - cut.start + offset, 4), "end": round(word.end - cut.start + offset, 4)}
                # Whisper can tokenize compounds as "tried", "-and", "-true".
                # Keep the compound together without changing its outer timing.
                if cut_words and re.match(r"^-[A-Za-z]", word.text) and item["start"] - cut_words[-1]["end"] < .2:
                    cut_words[-1]["text"] += word.text
                    cut_words[-1]["end"] = item["end"]
                else:
                    cut_words.append(item)
        result.extend(cut_words)
        offset += cut.end - cut.start
    return result


def ass_time(seconds: float):
    value = round(seconds * 100)
    h, value = divmod(value, 360000)
    m, value = divmod(value, 6000)
    s, cs = divmod(value, 100)
    return f"{h}:{m:02}:{s:02}.{cs:02}"


def clean(text: str):
    return text.replace("\\", "").replace("{", "").replace("}", "").replace("\n", " ").replace("\r", " ")


def ass_colour(hex_colour: str):
    r, g, b = hex_colour[1:3], hex_colour[3:5], hex_colour[5:7]
    return f"&H00{b}{g}{r}"


def build_ass(cuts: list[Cut], trans: Transcript, profile: Captions, size: tuple[int, int], accent: str, destination: Path):
    width, height = size
    preset = PRESETS[profile.style]
    vertical = height > width
    left, right = (95, 180) if vertical else (int(width * .06), int(width * .06))
    font_size = preset["font_size"] if vertical else 48
    if width == height:
        font_size = 45
    margin = int(height * (.30 if vertical else .10))
    alignment = {"safe-bottom": 2, "center": 5, "top": 8}[profile.position]
    if profile.position == "top":
        margin = int(height * .14)
    font = re.sub(r"[,\n\r]", "", profile.font)
    max_chars = max(12, int((width - left - right) / (font_size * .62)))
    if vertical:
        max_chars = min(max_chars, 25)
    words = output_words(cuts, trans)
    groups = []
    current: list[dict] = []
    for word in words:
        proposed = " ".join(w["text"] for w in current + [word])
        wrap = textwrap.wrap(proposed, width=max_chars)
        if current and (len(wrap) > profile.max_lines or word["start"] - current[-1]["end"] > .45):
            groups.append(current)
            current = []
        current.append(word)
        if len(current) >= preset["words"] or word["text"][-1:] in ".!?":
            groups.append(current)
            current = []
    if current:
        groups.append(current)
    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {width}
PlayResY: {height}
WrapStyle: 2
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,{font},{font_size},&H00FFFFFF,{ass_colour(accent)},&H00101419,&H60000000,{preset['bold']},0,0,0,100,100,0,0,1,{preset['outline']},0,{alignment},{left},{right},{margin},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    cues = []
    for group in groups:
        plain = " ".join(clean(w["text"]) for w in group)
        lines = textwrap.wrap(plain, width=max_chars)
        if len(lines) > profile.max_lines:
            raise StudioError("A caption cannot fit its safe zone. Adjust the transcript or caption font.")
        if profile.word_emphasis:
            # Karaoke timing follows word starts, including pauses, on the output timeline.
            parts = []
            count = 0
            for i, w in enumerate(group):
                text = clean(w["text"])
                sep = " " if count else ""
                if count and count + 1 + len(text) > max_chars:
                    sep, count = r"\N", 0
                duration = (group[i + 1]["start"] if i + 1 < len(group) else w["end"]) - w["start"]
                parts.append(sep + "{\\kf" + str(max(1, round(duration * 100))) + "}" + text)
                count += len(text) + (1 if count else 0)
            caption = "".join(parts)
        else:
            caption = r"\N".join(lines)
        start, end = group[0]["start"], group[-1]["end"]
        if round(end * 100) <= round(start * 100):
            raise StudioError("Caption cue is shorter than ASS timing precision")
        header += f"Dialogue: 0,{ass_time(start)},{ass_time(end)},Default,,0,0,0,,{caption}\n"
        cues.append({"start": start, "end": end, "text": plain, "lines": len(lines)})
    if not cues:
        raise StudioError("No caption words in selected ranges")
    atomic_text(destination, header)
    return {"cues": cues, "resolution": size, "safe_zone": {"left": left, "right": right, "margin_vertical": margin}, "max_lines": profile.max_lines, "word_timing": "ASR; needs human accuracy review"}
