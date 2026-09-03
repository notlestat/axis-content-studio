from __future__ import annotations

from pathlib import Path

from studio.models import Cut


def find_subject(video: Path, cut: Cut):
    """Conservative face proposal. Multiple/changing faces use fit; no identity claims."""
    try:
        import cv2
    except ImportError:
        return None, "OpenCV unavailable; full picture retained"
    if not hasattr(cv2, "CascadeClassifier") or not hasattr(cv2, "data"):
        return None, "OpenCV face detector unavailable; full picture retained"
    classifier = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")  # type: ignore[attr-defined]
    capture = cv2.VideoCapture(str(video))
    positions = []
    try:
        for fraction in (.1, .3, .5, .7, .9):
            capture.set(cv2.CAP_PROP_POS_MSEC, (cut.start + (cut.end - cut.start) * fraction) * 1000)
            ok, frame = capture.read()
            if not ok:
                return None, "Frame sampling failed; full picture retained"
            height, width = frame.shape[:2]
            scaled = cv2.resize(frame, (640, max(1, round(height * 640 / width))))
            faces = classifier.detectMultiScale(cv2.cvtColor(scaled, cv2.COLOR_BGR2GRAY), scaleFactor=1.1, minNeighbors=5, minSize=(35, 35))
            if len(faces) != 1:
                return None, "No unique face across the shot; review/manual speaker crop or full-picture fit"
            x, _, w, _ = faces[0]
            positions.append(float((x + w / 2) / 640))
    finally:
        capture.release()
    if max(positions) - min(positions) > .12:
        return None, "Subject changes position; review/manual reframing or full-picture fit"
    return sorted(positions)[len(positions) // 2], "Single stable face; automatic crop proposal, not verified active speaker"


def filter_for(size: tuple[int, int], center: float | None, punch: float, background: str, keyframes=None, start=0.0):
    width, height = size
    colour = background.lstrip("#")
    if center is None:
        return f"scale={width}:{height}:force_original_aspect_ratio=decrease:force_divisible_by=2,pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:color=0x{colour},setsar=1"
    scaled_w = round(width * punch / 2) * 2
    scaled_h = round(height * punch / 2) * 2
    position = f"{center:.6f}"
    for point in keyframes or []:
        position = f"if(gte(t,{max(0, point.timestamp-start):.6f}),{point.x:.6f},{position})"
    return f"scale={scaled_w}:{scaled_h}:force_original_aspect_ratio=increase:force_divisible_by=2,crop={width}:{height}:x='min(max(iw*({position})-{width}/2,0),iw-{width})':y='(ih-{height})/2',setsar=1"
