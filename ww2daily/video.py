"""Vertical short-video generator (9:16) for VK Clips / YouTube Shorts.

Builds a clip from a few archival images that each *fill* the vertical frame
(cover-crop + slow pan — no letterbox bands), with the spoken line shown as a
styled subtitle over a bottom gradient, a generated voiceover (edge-tts) and an
audible music bed. Pure pip toolchain: moviepy 2.x + imageio-ffmpeg + Pillow +
edge-tts (no system packages). Voiceover degrades gracefully: if synthesis is
unavailable, segments fall back to a fixed duration and the clip is silent
except for music.

Spec per segment:
    {"image": "<local path>", "text": "<line shown AND spoken>",
     "say": "<optional TTS override>"}
Legacy keys `caption`/`narration` are still accepted.
"""

import asyncio
import glob
import os
import tempfile

from PIL import Image
from moviepy import (AudioFileClip, CompositeAudioClip, CompositeVideoClip,
                     ImageClip, TextClip, concatenate_videoclips)

W, H = 1080, 1920
FPS = 30
FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
FALLBACK_SECONDS = 3.4           # per segment when no narration audio
VOICES = {"ru": "ru-RU-DmitryNeural", "en": "en-US-GuyNeural"}
RATE = {"ru": "+11%", "en": "+8%"}  # a touch brisker -> fits the <=20s budget
MUSIC_VOL = 0.34                 # audible under the (full-scale) voice
OVERSCALE = 1.18                 # image is prepped larger than frame, then panned
MUSIC_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "assets", "music")


# --- voiceover ---------------------------------------------------------------

def _trust_system_cas() -> None:
    """Point edge-tts at the system CA bundle.

    edge-tts hardcodes an SSL context built from certifi. Behind an
    SSL-intercepting proxy (as in the cloud routine), certifi lacks the
    proxy's CA, so synthesis fails handshake. SSL_CERT_FILE /
    REQUESTS_CA_BUNDLE point at a bundle that *does* include it; rebuild the
    edge-tts context from there when available."""
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
    except Exception as exc:  # network/proxy/etc — fall back to silent
        print(f"[video] TTS unavailable ({type(exc).__name__}); silent segment.")
        return False


# --- image preparation -------------------------------------------------------

def _prep_cover(src: str, dst: str) -> str:
    """Cover-crop the source to the vertical frame (oversized by OVERSCALE so it
    can be panned without revealing edges). Returns 'h' or 'v' as a pan hint
    based on the *original* aspect ratio."""
    img = Image.open(src).convert("RGB")
    orient = "h" if img.width >= img.height else "v"
    tw, th = int(W * OVERSCALE), int(H * OVERSCALE)
    scale = max(tw / img.width, th / img.height)
    img = img.resize((max(tw, round(img.width * scale)),
                      max(th, round(img.height * scale))), Image.LANCZOS)
    left = (img.width - tw) // 2
    top = (img.height - th) // 2
    img = img.crop((left, top, left + tw, top + th))
    img.save(dst, quality=92)
    return orient


def _gradient_overlay(tmp: str) -> str:
    """A reusable bottom-up dark gradient so subtitles stay legible on any
    image. Transparent across the top ~55%, ramping to near-opaque black."""
    path = os.path.join(tmp, "grad.png")
    grad = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    px = grad.load()
    start = int(H * 0.52)
    for y in range(start, H):
        a = int(210 * (y - start) / (H - start))
        for x in range(W):
            px[x, y] = (0, 0, 0, a)
    grad.save(path)
    return path


# --- building ----------------------------------------------------------------

def _pan(orient: str, idx: int, duration: float):
    """A slow linear pan that always keeps the oversized image covering the
    frame. Alternates direction per segment for variety."""
    head_x = int(W * OVERSCALE) - W
    head_y = int(H * OVERSCALE) - H
    fwd = (idx % 2 == 0)
    if orient == "h":                      # landscape -> reveal width
        y = -head_y // 2
        x0, x1 = (-head_x * 0.12, -head_x * 0.88) if fwd else (-head_x * 0.88, -head_x * 0.12)
        return lambda t: (x0 + (x1 - x0) * (t / duration), y)
    x = -head_x // 2                       # portrait -> reveal height
    y0, y1 = (-head_y * 0.12, -head_y * 0.80) if fwd else (-head_y * 0.80, -head_y * 0.12)
    return lambda t: (x, y0 + (y1 - y0) * (t / duration))


def _segment(image_path: str, text: str, duration: float, grad_path: str,
             tmp: str, idx: int):
    cover_path = os.path.join(tmp, f"cv_{idx}.jpg")
    orient = _prep_cover(image_path, cover_path)

    img = (ImageClip(cover_path).with_duration(duration)
           .with_position(_pan(orient, idx, duration)))
    grad = ImageClip(grad_path, transparent=True).with_duration(duration)

    layers = [img, grad]
    if text:
        txt = (TextClip(text=text, font=FONT, font_size=62, color="white",
                        method="caption", size=(int(W * 0.84), None),
                        text_align="center", stroke_color="black", stroke_width=3)
               .with_duration(duration).with_position(("center", int(H * 0.70))))
        try:
            from moviepy import vfx
            txt = txt.with_effects([vfx.CrossFadeIn(0.25)])
        except Exception:
            pass
        layers.append(txt)
    return CompositeVideoClip(layers, size=(W, H))


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


def _line(seg: dict, key_text: str, key_say: str) -> tuple[str, str]:
    """(subtitle, tts) from a segment, honouring legacy keys."""
    text = seg.get("text") or seg.get("caption") or ""
    say = seg.get("say") or seg.get("narration") or text
    return text, say


def build(spec: dict, out_path: str) -> str:
    """spec: {lang, segments:[{image, text, say?}]}. `image` is a local path."""
    lang = spec.get("lang", "ru")
    tmp = tempfile.mkdtemp(prefix="ww2vid_")
    grad_path = _gradient_overlay(tmp)
    clips, narration_audio = [], []
    cursor = 0.0

    for i, seg in enumerate(spec["segments"]):
        text, say = _line(seg, "text", "say")
        audio_path = os.path.join(tmp, f"v_{i}.mp3")
        has_voice = synthesize(say, lang, audio_path)
        if has_voice:
            a = AudioFileClip(audio_path)
            duration = a.duration + 0.35
            narration_audio.append(a.with_start(cursor + 0.12))
        else:
            duration = FALLBACK_SECONDS
        clips.append(_segment(seg["image"], text, duration, grad_path, tmp, i))
        cursor += duration

    video = concatenate_videoclips(clips, method="compose").with_fps(FPS)
    total = video.duration

    audio_tracks = list(narration_audio)
    music = _music_bed(total)
    if music is not None:
        audio_tracks.append(music)
    if audio_tracks:
        video = video.with_audio(CompositeAudioClip(audio_tracks))

    video.write_videofile(out_path, codec="libx264", audio_codec="aac",
                          fps=FPS, preset="veryfast", threads=os.cpu_count() or 4,
                          ffmpeg_params=["-pix_fmt", "yuv420p"], logger=None)
    return out_path
