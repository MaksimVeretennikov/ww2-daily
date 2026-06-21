#!/usr/bin/env python3
"""Render the vertical short video(s) from run/video_spec.json (written by Claude).

video_spec.json (per language "ru"/"en"):
{
  "ru": {
    "lines": [{"text": "shown & spoken", "say": "optional TTS override"}, ...],
    "shots": [{"image": "path|url"} | {"video": "path|url", "start": s, "dur": d},
              ... optional "weight" for relative on-screen time]
  }
}
Legacy {"segments": [{image, caption, narration}]} is still accepted.

Downloads any remote media, then renders run/video_<lang>.mp4 (1080x1920,
voiceover + optional music). Languages with no content are skipped.
"""

import json
import os

import _bootstrap  # noqa: F401
from ww2daily import commons, video

SPEC = os.path.join(_bootstrap.RUN_DIR, "video_spec.json")
MEDIA_DIR = os.path.join(_bootstrap.RUN_DIR, "vid_media")


def _localize(items: list, tag: str) -> list:
    """Resolve remote image/video URLs to local files, in place-ish."""
    os.makedirs(MEDIA_DIR, exist_ok=True)
    out = []
    for i, it in enumerate(items):
        it = dict(it)
        for key in ("image", "video"):
            src = it.get(key) or it.get(f"{key}_url")
            if not src:
                continue
            if src.startswith("http"):
                ext = os.path.splitext(src.split("?")[0])[1] or (".mp4" if key == "video" else ".jpg")
                local = os.path.join(MEDIA_DIR, f"{tag}_{key}_{i}{ext}")
                commons.download(src, local)
                it[key] = local
            else:
                it[key] = src
        out.append(it)
    return out


def main() -> None:
    with open(SPEC, encoding="utf-8") as fh:
        spec = json.load(fh)

    made = []
    for lang in ("ru", "en"):
        block = spec.get(lang)
        if not block:
            continue
        has_new = block.get("shots") or block.get("lines")
        has_old = block.get("segments")
        if not (has_new or has_old):
            continue

        if block.get("shots"):
            block = {**block, "shots": _localize(block["shots"], lang)}
        if block.get("segments"):
            block = {**block, "segments": _localize(block["segments"], lang)}

        out = os.path.join(_bootstrap.RUN_DIR, f"video_{lang}.mp4")
        video.build(block, out, lang)
        size = os.path.getsize(out)
        made.append((lang, out, size))
        print(f"[{lang}] {out} ({size} bytes)")

    if not made:
        raise SystemExit("video_spec.json has no lines/shots/segments for ru or en.")
    print("\nRendered:", ", ".join(f"{l}->{os.path.basename(p)}" for l, p, _ in made))


if __name__ == "__main__":
    main()
