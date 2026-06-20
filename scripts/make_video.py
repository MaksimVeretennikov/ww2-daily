#!/usr/bin/env python3
"""Render the vertical short video(s) from run/video_spec.json (written by Claude).

video_spec.json:
{
  "ru": {"segments": [{"image_url": "...", "caption": "...", "narration": "..."}, ...]},
  "en": {"segments": [...]}          // either or both languages
}

Downloads each segment image, renders run/video_<lang>.mp4 (1080x1920, voiceover
+ optional music). Languages with no segments are skipped.
"""

import json
import os

import _bootstrap  # noqa: F401
from ww2daily import commons, video

SPEC = os.path.join(_bootstrap.RUN_DIR, "video_spec.json")
IMG_DIR = os.path.join(_bootstrap.RUN_DIR, "vid_imgs")


def _localize_images(segments: list) -> list:
    os.makedirs(IMG_DIR, exist_ok=True)
    out = []
    for i, seg in enumerate(segments):
        src = seg.get("image") or seg.get("image_url")
        if src and src.startswith("http"):
            ext = os.path.splitext(src.split("?")[0])[1] or ".jpg"
            local = os.path.join(IMG_DIR, f"img_{i}{ext}")
            commons.download(src, local)
            seg = {**seg, "image": local}
        else:
            seg = {**seg, "image": src}
        out.append(seg)
    return out


def main() -> None:
    with open(SPEC, encoding="utf-8") as fh:
        spec = json.load(fh)

    made = []
    for lang in ("ru", "en"):
        block = spec.get(lang)
        if not block or not block.get("segments"):
            continue
        segments = _localize_images(block["segments"])
        out = os.path.join(_bootstrap.RUN_DIR, f"video_{lang}.mp4")
        video.build({"lang": lang, "segments": segments}, out)
        size = os.path.getsize(out)
        made.append((lang, out, size))
        print(f"[{lang}] {out} ({size} bytes)")

    if not made:
        raise SystemExit("video_spec.json has no segments for ru or en.")
    print("\nRendered:", ", ".join(f"{l}->{os.path.basename(p)}" for l, p, _ in made))


if __name__ == "__main__":
    main()
