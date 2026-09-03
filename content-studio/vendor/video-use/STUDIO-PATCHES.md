# Local patch record

Base: browser-use/video-use at 9575612f066aa517354790a645fd90f9f95a743b.

helpers/render.py, extract_segment:
- Add optional audio_track=0 keyword parameter.
- Explicitly map 0:v:0 and the selected 0:a track.
- Encode two audio channels for consistent multi-source concat.

Everything else in vendor/video-use/helpers is unchanged. The MIT license is
retained. Adapter behavior lives in studio/upstream.py and studio/rendering.py.
