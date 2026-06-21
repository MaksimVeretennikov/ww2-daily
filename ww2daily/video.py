"""Vertical short-video generator (9:16) for VK Clips / YouTube Shorts.

Fast-cut style inspired by history Shorts: the narration is split into short
*lines* (each shown as a pop-in subtitle in the lower-centre, where the eye
rests), while the *visuals* are a separate, denser track of shots cut quickly
to fill the voiceover. Shots can be images or short archival video clips.

Framing rule (matches what reads well vertically):
  - portrait/tall source  -> fills the whole frame (cover) with a slow zoom;
  - landscape/wide source  -> shown whole, centred, over its own blurred,
    darkened background (no ugly hard crop, no empty black bands).

Pure pip toolchain: moviepy 2.x + imageio-ffmpeg + Pillow + edge-tts. Voiceover
degrades gracefully: if synthesis is unavailable, lines fall back to a fixed
duration and the clip is silent except for music.

Spec per language:
    {"lines": [{"text": "<shown & spoken>", "say": "<optional TTS override>"}],
     "shots": [{"image": "<path>"} | {"video": "<path>", "start": s, "dur": d},
               ... each may carry "weight" for relative on-screen time]}
Legacy `segments` (image+caption+narration) is still accepted.
"""

import asyncio
import glob
import os
import tempfile

from PIL import Image, ImageDraw, ImageFilter, ImageFont
from moviepy import (AudioFileClip, CompositeAudioClip, CompositeVideoClip,
                     ImageClip, VideoFileClip, concatenate_videoclips)

W, H = 1080, 1920
FPS = 30
FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
FALLBACK_LINE = 2.2              # per line when no narration audio
LEAD_IN = 0.12                   # silence before first line
GAP = 0.10                       # silence between lines
TAIL = 0.30                      # silence after last line
SUB_Y = 0.58                     # subtitle centre, fraction of height (lower-centre)
VOICES = {"ru": "ru-RU-DmitryNeural", "en": "en-US-GuyNeural"}
RATE = {"ru": "+20%", "en": "+16%"}   # brisk delivery
MUSIC_VOL = 0.30
MUSIC_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "assets", "music")


# --- voiceover ---------------------------------------------------------------

def _trust_system_cas() -> None:
    """Point edge-tts at the system CA bundle (needed behind the cloud proxy)."""
    bundle = os.environ.get("SSL_CERT_FILE") or os.environ.get("REQUESTS_CA_BUNDLE")
    if not bundle or not os.path.exists(bundle):
        return
    try:
        import ssl

        import edge_tts.communicate as _ec
        _ec._SSL_CTX = ssl.create_default_context(cafile=bundle)
    except Exception:
        pass


def synthesize(text: str, lang: str, out_path: str) -> bool:
    """edge-tts -> mp3. Returns True on success, False if unavailable."""
    if not text:
        return False
    try:
        import edge_tts
        _trust_system_cas()

        async def _run():
            await edge_tts.Communicate(
                text, VOICES.get(lang, VOICES["en"]), rate=RATE.get(lang, "+0%")
            ).save(out_path)

        asyncio.run(_run())
        return os.path.exists(out_path) and os.path.getsize(out_path) > 0
    except Exception as exc:
        print(f"[video] TTS unavailable ({type(exc).__name__}); silent line.")
        return False


# --- image preparation -------------------------------------------------------

def _prep_cover(src: str, dst: str) -> None:
    """Cover-crop the source to exactly the frame (for portrait sources)."""
    img = Image.open(src).convert("RGB")
    scale = max(W / img.width, H / img.height)
    img = img.resize((max(W, round(img.width * scale)),
                      max(H, round(img.height * scale))), Image.LANCZOS)
    left = (img.width - W) // 2
    top = (img.height - H) // 2
    img.crop((left, top, left + W, top + H)).save(dst, quality=92)


def _prep_fit(src: str, dst: str) -> None:
    """Fit a landscape source whole inside the frame (full width, centred)."""
    img = Image.open(src).convert("RGB")
    scale = min(W / img.width, (H * 0.86) / img.height)
    img.resize((round(img.width * scale), round(img.height * scale)),
               Image.LANCZOS).save(dst, quality=92)


def _prep_blur(src: str, dst: str) -> None:
    """Blurred, darkened full-frame background for letterboxed landscapes."""
    img = Image.open(src).convert("RGB")
    scale = max(W / img.width, H / img.height)
    img = img.resize((round(img.width * scale), round(img.height * scale)))
    left = (img.width - W) // 2
    top = (img.height - H) // 2
    img = img.crop((left, top, left + W, top + H))
    img.filter(ImageFilter.GaussianBlur(45)).point(lambda p: int(p * 0.5)).save(dst, quality=86)


# --- shots -------------------------------------------------------------------

def _shot_image(src: str, dur: float, idx: int, tmp: str):
    img = Image.open(src)
    aspect = img.width / img.height
    if aspect < 0.85:                       # clearly portrait -> fill the frame
        cov = os.path.join(tmp, f"cov_{idx}.jpg")
        _prep_cover(src, cov)
        clip = (ImageClip(cov).with_duration(dur)
                .resized(lambda t: 1 + 0.05 * t / dur).with_position("center"))
        return CompositeVideoClip([clip], size=(W, H))
    # landscape / square -> whole image over its blurred background
    fg = os.path.join(tmp, f"fg_{idx}.jpg")
    bg = os.path.join(tmp, f"bg_{idx}.jpg")
    _prep_fit(src, fg)
    _prep_blur(src, bg)
    bgc = (ImageClip(bg).with_duration(dur)
           .resized(lambda t: 1 + 0.05 * t / dur).with_position("center"))
    fgc = (ImageClip(fg).with_duration(dur)
           .resized(lambda t: 1 + 0.02 * t / dur).with_position("center"))
    return CompositeVideoClip([bgc, fgc], size=(W, H))


def _shot_video(src: str, dur: float, start: float):
    """Short archival clip, cover-fit to the frame."""
    v = VideoFileClip(src)
    seg = v.subclipped(start, min(start + dur, v.duration))
    scale = max(W / seg.w, H / seg.h)
    seg = seg.resized(scale)
    x, y = (seg.w - W) / 2, (seg.h - H) / 2
    seg = seg.cropped(x1=x, y1=y, x2=x + W, y2=y + H).with_duration(dur)
    return CompositeVideoClip([seg], size=(W, H))


# --- subtitles ---------------------------------------------------------------

def _wrap(draw, text, font, max_w):
    words, lines, cur = text.split(), [], ""
    for w in words:
        t = (cur + " " + w).strip()
        if not cur or draw.textlength(t, font=font) <= max_w:
            cur = t
        else:
            lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines


def _subtitle(text: str, start: float, dur: float, idx: int, tmp: str):
    """Lower-centre subtitle on a soft translucent pill, popping in with a
    small scale-up. Rendered with Pillow for full control over the look."""
    font = ImageFont.truetype(FONT, 56)
    probe = ImageDraw.Draw(Image.new("RGB", (8, 8)))
    lines = _wrap(probe, text, font, int(W * 0.76))
    asc, desc = font.getmetrics()
    lh, spacing, pad_x, pad_y = asc + desc, 10, 34, 22
    text_w = max(int(probe.textlength(l, font=font)) for l in lines)
    box_w = text_w + 2 * pad_x
    box_h = lh * len(lines) + spacing * (len(lines) - 1) + 2 * pad_y

    img = Image.new("RGBA", (box_w, box_h), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([0, 0, box_w - 1, box_h - 1], radius=26, fill=(0, 0, 0, 120))
    y = pad_y
    for l in lines:
        x = (box_w - probe.textlength(l, font=font)) / 2
        d.text((x, y), l, font=font, fill=(255, 255, 255, 255),
               stroke_width=3, stroke_fill=(0, 0, 0, 255))
        y += lh + spacing
    png = os.path.join(tmp, f"sub_{idx}.png")
    img.save(png)

    def scale(t):
        k = min(t / 0.16, 1.0)
        k = k * k * (3 - 2 * k)             # smoothstep
        return 0.82 + 0.18 * k

    def pos(t):
        s = scale(t)
        return ((W - box_w * s) / 2, H * SUB_Y - box_h * s / 2)

    clip = (ImageClip(png, transparent=True).with_duration(dur + GAP)
            .resized(scale).with_position(pos).with_start(start))
    try:
        from moviepy import vfx
        clip = clip.with_effects([vfx.CrossFadeIn(0.12)])
    except Exception:
        pass
    return clip


# --- audio -------------------------------------------------------------------

def _music_bed(total: float):
    tracks = sorted(glob.glob(os.path.join(MUSIC_DIR, "*.mp3")) +
                    glob.glob(os.path.join(MUSIC_DIR, "*.m4a")))
    if not tracks:
        return None
    import random
    track = AudioFileClip(random.choice(tracks))
    track = track.subclipped(0, min(total, track.duration))
    try:
        track = track.with_volume_scaled(MUSIC_VOL)
    except Exception:
        pass
    return track


# --- building ----------------------------------------------------------------

def _normalize(block: dict) -> tuple[list, list]:
    """Return (lines, flat_shots). If every line carries its own `shots`,
    flat_shots is None and visuals are aligned to the narration lines.
    Otherwise flat_shots is a list spread across the whole timeline."""
    if block.get("lines"):
        lines = block["lines"]
        if lines and all(ln.get("shots") for ln in lines):
            return lines, None
        return lines, block.get("shots", [])
    lines, shots = [], []
    for seg in block.get("segments", []):
        text = seg.get("text") or seg.get("caption") or ""
        lines.append({"text": text, "say": seg.get("say") or seg.get("narration") or text})
        shots.append({"image": seg.get("image"), "video": seg.get("video")})
    return lines, shots


def _shot(s: dict, dur: float, idx: int, tmp: str):
    if s.get("video"):
        return _shot_video(s["video"], dur, float(s.get("start", 0.0)))
    return _shot_image(s["image"], dur, idx, tmp)


def build(block: dict, out_path: str, lang: str = "ru") -> str:
    tmp = tempfile.mkdtemp(prefix="ww2vid_")
    lines, flat_shots = _normalize(block)

    # 1) voiceover + subtitle timeline; record each line's start/duration
    narration, subs = [], []
    starts, durs = [], []
    t = LEAD_IN
    for i, ln in enumerate(lines):
        text = ln.get("text") or ""
        say = ln.get("say") or text
        ap = os.path.join(tmp, f"v_{i}.mp3")
        if synthesize(say, lang, ap):
            a = AudioFileClip(ap)
            d = a.duration
            narration.append(a.with_start(t))
        else:
            d = FALLBACK_LINE
        starts.append(t)
        durs.append(d)
        if text:
            subs.append(_subtitle(text, t, d, i, tmp))
        t += d + GAP
    total = t - GAP + TAIL

    # 2) visual track
    shot_clips, sidx = [], 0
    if flat_shots is None:
        # aligned: each line's shots fill that line's on-screen window, so a cut
        # lands on every new line (plus extra cuts inside multi-shot lines)
        win_start = [0.0] + starts[1:]
        win_end = starts[1:] + [total]
        for i, ln in enumerate(lines):
            shots = ln["shots"]
            span = (win_end[i] - win_start[i]) / len(shots)
            for s in shots:
                shot_clips.append(_shot(s, span, sidx, tmp))
                sidx += 1
    else:
        # decoupled: spread flat shots across the whole clip by weight
        weights = [float(s.get("weight", 1.0)) for s in flat_shots] or [1.0]
        wsum = sum(weights)
        sdurs = [total * w / wsum for w in weights]
        sdurs[-1] += total - sum(sdurs)
        for s, d in zip(flat_shots, sdurs):
            shot_clips.append(_shot(s, d, sidx, tmp))
            sidx += 1
    visual = concatenate_videoclips(shot_clips, method="compose")

    # 3) compose subtitles over visuals
    video = CompositeVideoClip([visual, *subs], size=(W, H)).with_duration(total).with_fps(FPS)

    # 4) audio
    audio_tracks = list(narration)
    music = _music_bed(total)
    if music is not None:
        audio_tracks.append(music)
    if audio_tracks:
        video = video.with_audio(CompositeAudioClip(audio_tracks))

    video.write_videofile(out_path, codec="libx264", audio_codec="aac",
                          fps=FPS, preset="veryfast", threads=os.cpu_count() or 4,
                          ffmpeg_params=["-pix_fmt", "yuv420p"], logger=None)
    return out_path
