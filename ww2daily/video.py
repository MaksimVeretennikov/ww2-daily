"""Vertical short-video generator (9:16) for VK Clips / YouTube Shorts.

Builds a clip from a few archival images with a slow Ken Burns zoom, on-screen
captions and an optional generated voiceover (edge-tts) plus a royalty-free
music bed. Pure pip toolchain: moviepy 2.x + imageio-ffmpeg + Pillow + edge-tts
(no system packages). Voiceover degrades gracefully: if synthesis is
unavailable, segments fall back to a fixed duration and the clip is silent
except for music.
"""

import asyncio
import glob
import os
import tempfile

from PIL import Image, ImageFilter
from moviepy import (AudioFileClip, CompositeAudioClip, CompositeVideoClip,
                     ImageClip, TextClip, concatenate_videoclips)

from . import config

W, H = 1080, 1920
FPS = 30
FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
FALLBACK_SECONDS = 4.0           # per segment when no narration audio
VOICES = {"ru": "ru-RU-DmitryNeural", "en": "en-US-GuyNeural"}
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
            await edge_tts.Communicate(text, VOICES.get(lang, VOICES["en"])).save(out_path)

        asyncio.run(_run())
        return os.path.exists(out_path) and os.path.getsize(out_path) > 0
    except Exception as exc:  # network/proxy/etc — fall back to silent
        print(f"[video] TTS unavailable ({type(exc).__name__}); silent segment.")
        return False


# --- image preparation -------------------------------------------------------

def _prep_background(src: str, dst: str) -> None:
    """Blurred, darkened full-frame background from the source image."""
    img = Image.open(src).convert("RGB")
    scale = max(W / img.width, H / img.height)
    img = img.resize((int(img.width * scale), int(img.height * scale)))
    left = (img.width - W) // 2
    top = (img.height - H) // 2
    img = img.crop((left, top, left + W, top + H))
    img = img.filter(ImageFilter.GaussianBlur(40)).point(lambda p: int(p * 0.45))
    img.save(dst, quality=88)


def _prep_foreground(src: str, dst: str) -> None:
    """Source image fitted to the width, on transparent canvas (centered later)."""
    img = Image.open(src).convert("RGB")
    target_w = int(W * 0.94)
    scale = target_w / img.width
    img = img.resize((target_w, int(img.height * scale)))
    img.save(dst, quality=92)


# --- building ----------------------------------------------------------------

def _segment(image_path: str, caption: str, duration: float, tmp: str, idx: int):
    bg_path = os.path.join(tmp, f"bg_{idx}.jpg")
    fg_path = os.path.join(tmp, f"fg_{idx}.jpg")
    _prep_background(image_path, bg_path)
    _prep_foreground(image_path, fg_path)

    bg = (ImageClip(bg_path).with_duration(duration)
          .resized(lambda t: 1 + 0.05 * t).with_position("center"))
    fg = (ImageClip(fg_path).with_duration(duration)
          .resized(lambda t: 1 + 0.04 * t).with_position("center"))

    layers = [bg, fg]
    if caption:
        txt = (TextClip(text=caption, font=FONT, font_size=52, color="white",
                        method="caption", size=(int(W * 0.86), None),
                        text_align="center", stroke_color="black", stroke_width=2)
               .with_duration(duration).with_position(("center", int(H * 0.74))))
        layers.append(txt)
    return CompositeVideoClip(layers, size=(W, H))


def _music_bed(total: float, tmp: str):
    tracks = sorted(glob.glob(os.path.join(MUSIC_DIR, "*.mp3")) +
                    glob.glob(os.path.join(MUSIC_DIR, "*.m4a")))
    if not tracks:
        return None
    import random
    track = AudioFileClip(random.choice(tracks))
    track = track.subclipped(0, min(total, track.duration))
    try:
        track = track.with_volume_scaled(0.18)
    except Exception:
        pass
    return track


def build(spec: dict, out_path: str) -> str:
    """spec: {lang, segments:[{image, caption, narration}], (title/cta optional)}.
    `image` is a local file path. Renders out_path (mp4)."""
    lang = spec.get("lang", "ru")
    tmp = tempfile.mkdtemp(prefix="ww2vid_")
    clips, narration_audio = [], []
    cursor = 0.0

    for i, seg in enumerate(spec["segments"]):
        audio_path = os.path.join(tmp, f"v_{i}.mp3")
        has_voice = synthesize(seg.get("narration", ""), lang, audio_path)
        if has_voice:
            a = AudioFileClip(audio_path)
            duration = a.duration + 0.4
            narration_audio.append(a.with_start(cursor))
        else:
            duration = FALLBACK_SECONDS
        clips.append(_segment(seg["image"], seg.get("caption", ""), duration, tmp, i))
        cursor += duration

    video = concatenate_videoclips(clips, method="compose").with_fps(FPS)
    total = video.duration

    audio_tracks = list(narration_audio)
    music = _music_bed(total, tmp)
    if music is not None:
        audio_tracks.append(music)
    if audio_tracks:
        video = video.with_audio(CompositeAudioClip(audio_tracks))

    video.write_videofile(out_path, codec="libx264", audio_codec="aac",
                          fps=FPS, preset="medium", logger=None)
    return out_path
