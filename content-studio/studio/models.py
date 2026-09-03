from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

Seconds = Annotated[float, Field(ge=0, allow_inf_nan=False)]
Positive = Annotated[float, Field(gt=0, allow_inf_nan=False)]
Score = Annotated[float, Field(ge=0, le=10, allow_inf_nan=False)]
Identifier = Annotated[str, Field(pattern=r"^[a-z0-9][a-z0-9-]{0,79}$")]


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True, validate_default=True, populate_by_name=True, serialize_by_alias=True)


class Longform(Model):
    enabled: bool = False
    pacing: str = "Natural conversation; preserve pauses for emphasis and speaker handoffs."
    target_duration: Positive | None = None
    remove_dead_space: bool = True
    remove_filler: bool = False
    b_roll: bool = False
    subtitles: bool = False
    motion_graphics: bool = True


class Shortform(Model):
    enabled: bool = True
    clips_per_video: int = Field(default=5, ge=1, le=30)
    min_duration: Positive = 25
    max_duration: Positive = 75
    aspect_ratio: Literal["9:16", "1:1", "16:9"] = "9:16"
    pacing: str = "Premium founder content; keep complete ideas and natural delivery."
    reframe: Literal["auto", "fit", "manual"] = "auto"

    @model_validator(mode="after")
    def valid_durations(self):
        if self.min_duration > self.max_duration:
            raise ValueError("min_duration must not exceed max_duration")
        return self


class Captions(Model):
    enabled: bool = True
    style: Literal["clean", "minimal", "bold", "podcast", "creator"] = "clean"
    font: str = "Arial"
    position: Literal["safe-bottom", "center", "top"] = "safe-bottom"
    max_lines: int = Field(default=2, ge=1, le=2)
    word_emphasis: bool = False


class Graphics(Model):
    enabled: bool = True
    engine: Literal["hyperframes", "remotion", "pil", "auto"] = "hyperframes"
    style: str = "Restrained typography, clean diagrams, generous space, no stock stickers."
    frequency: Literal["off", "sparse", "moderate"] = "sparse"


class Brand(Model):
    primary_colour: str = Field(default="#141820", pattern=r"^#[0-9A-Fa-f]{6}$")
    secondary_colour: str = Field(default="#F4F3EE", pattern=r"^#[0-9A-Fa-f]{6}$")
    accent_colour: str = Field(default="#A8D5BA", pattern=r"^#[0-9A-Fa-f]{6}$")
    fonts: list[str] = Field(default_factory=lambda: ["Arial"], min_length=1)
    logo: str | None = None


class ContentPreferences(Model):
    preferred_topics: list[str] = Field(default_factory=list)
    avoid_topics: list[str] = Field(default_factory=list)
    preferred_hooks: list[str] = Field(default_factory=lambda: ["Specific problem", "Unexpected lesson"])
    CTA_style: str = "One relevant question or a calm invitation. No invented offers."


class Client(Model):
    name: str = Field(min_length=1)
    platforms: list[str] = Field(default_factory=lambda: ["instagram", "tiktok", "youtube"])
    longform: Longform = Field(default_factory=Longform)
    shortform: Shortform = Field(default_factory=Shortform)
    captions: Captions = Field(default_factory=Captions)
    graphics: Graphics = Field(default_factory=Graphics)
    brand: Brand = Field(default_factory=Brand)
    content_preferences: ContentPreferences = Field(default_factory=ContentPreferences)
    creative_notes: list[str] = Field(default_factory=list)


class Word(Model):
    text: str = Field(min_length=1)
    start: Seconds
    end: Seconds
    type: Literal["word", "audio_event"] = "word"
    speaker_id: str | None = None

    @model_validator(mode="after")
    def interval(self):
        if self.end <= self.start:
            raise ValueError("Word end must follow start")
        return self


class SourceTranscript(Model):
    source: Identifier
    source_sha256: str
    duration: Positive
    provider: str
    model: str
    language: str | None = None
    audio_track: int = Field(default=0, ge=0)
    words: list[Word] = Field(min_length=1)
    warnings: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def timeline(self):
        starts = [w.start for w in self.words]
        if starts != sorted(starts):
            raise ValueError("Transcript words must be sorted by start time")
        if any(w.end > self.duration + 0.25 for w in self.words):
            raise ValueError("Transcript extends beyond source duration")
        return self


class Transcript(Model):
    version: Literal[1] = 1
    sources: list[SourceTranscript] = Field(min_length=1)


class CropPoint(Model):
    timestamp: Seconds
    x: float = Field(ge=0, le=1, allow_inf_nan=False)


class Cut(Model):
    source: Identifier
    start: Seconds
    end: Positive
    reason: str = Field(min_length=1)
    crop_x: float | None = Field(default=None, ge=0, le=1, allow_inf_nan=False)
    punch_in: float = Field(default=1, ge=1, le=1.15, allow_inf_nan=False)
    crop_keyframes: list[CropPoint] = Field(default_factory=list)

    @model_validator(mode="after")
    def interval(self):
        if self.end <= self.start:
            raise ValueError("Cut end must follow start")
        times = [p.timestamp for p in self.crop_keyframes]
        if times != sorted(set(times)) or any(t < self.start or t >= self.end for t in times):
            raise ValueError("Crop keyframes must be sorted, unique source times inside the cut")
        return self


class Scores(Model):
    hook: Score
    clarity: Score
    standalone_value: Score
    retention: Score
    novelty: Score
    overall: Score


class Copy(Model):
    hook: str = Field(min_length=1)
    title: str = Field(min_length=1)
    caption: str = Field(min_length=1)
    youtube_title: str = Field(min_length=1, max_length=100)
    description: str = Field(min_length=1)
    linkedin: str = Field(min_length=1)
    x_post: str = Field(min_length=1, max_length=280)
    alternative_hooks: list[str] = Field(min_length=3, max_length=3)
    alternative_titles: list[str] = Field(min_length=3, max_length=3)
    cta: str = Field(min_length=1)


class Candidate(Model):
    id: Identifier
    source: Identifier
    start_time: Seconds
    end_time: Positive
    hook: str = Field(min_length=1)
    summary: str = Field(min_length=1)
    topic: str = Field(min_length=1)
    scores: Scores
    reason_selected: str = Field(min_length=1)
    cuts: list[Cut] = Field(default_factory=list)
    content_copy: Copy | None = Field(default=None, alias="copy")


VisualType = Literal["NUMBER", "STATISTIC", "LIST", "FRAMEWORK", "COMPARISON", "TIMELINE", "QUOTE", "PROCESS", "WEBSITE", "PRODUCT", "UI", "GRAPH", "DIAGRAM", "KEY_PHRASE"]


class Visual(Model):
    id: Identifier
    source: Identifier
    timestamp: Seconds
    duration: Positive = 5
    type: VisualType
    spoken_context: str = Field(min_length=1)
    visual_concept: str = Field(min_length=1)
    recommended_engine: Literal["hyperframes", "remotion", "pil"] = "hyperframes"
    priority: Literal["high", "medium", "low"] = "medium"
    target: str = "longform"
    headline: str = Field(min_length=1, max_length=65)
    lines: list[str] = Field(default_factory=list, max_length=4)


class Coverage(Model):
    source: Identifier
    start: Seconds
    end: Positive
    summary: str = Field(min_length=1)


class Analysis(Model):
    version: Literal[1] = 1
    input_digest: str
    strategy: str = Field(min_length=20)
    coverage: list[Coverage] = Field(min_length=1)
    candidates: list[Candidate] = Field(default_factory=list, max_length=30)
    shortage_reason: str | None = None
    longform: list[Cut] = Field(default_factory=list)
    longform_scope: Literal["full", "representative-section"] = "full"
    youtube_copy: str = ""
    thumbnail_notes: str = ""
    visuals: list[Visual] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class Rates(Model):
    transcription_per_minute_usd: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    llm_input_per_million_usd: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    llm_output_per_million_usd: float | None = Field(default=None, ge=0, allow_inf_nan=False)


class Settings(Model):
    transcription: Literal["local", "elevenlabs"] = "local"
    local_model: str = "small.en"
    language: str | None = "en"
    audio_track: int = Field(default=0, ge=0)
    fps: int = Field(default=30, ge=24, le=60)
    cut_padding: float = Field(default=0.08, ge=0.03, le=0.2)
    rates: Rates = Field(default_factory=Rates)
