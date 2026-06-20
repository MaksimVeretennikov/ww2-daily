"""Cross-post to a VK community you own.

Posting to a community wall with a photo needs a USER access token (scopes
wall,photos,groups,offline). VK community tokens cannot upload wall photos
(photos.getWallUploadServer fails with error 27), so we use the owner's user
token. The image is uploaded directly from the local file — no proxy needed.
"""

import re

from . import config, http

API = "https://api.vk.com/method/"


def is_enabled() -> bool:
    return bool(config.VK_ACCESS_TOKEN and config.VK_GROUP_ID)


def _strip_html(s: str) -> str:
    return re.sub(r"<[^>]+>", "", s or "").strip()


def _call(method: str, **params) -> dict:
    params.setdefault("access_token", config.VK_ACCESS_TOKEN)
    params.setdefault("v", config.VK_API_VERSION)
    resp = http.session().post(API + method, data=params,
                               timeout=config.HTTP_TIMEOUT)
    resp.raise_for_status()
    data = resp.json()
    if "error" in data:
        raise RuntimeError(f"VK error {data['error'].get('error_code')}: "
                           f"{data['error'].get('error_msg')}")
    return data["response"]


def _upload_photo(image_path: str, gid: str) -> str:
    server = _call("photos.getWallUploadServer", group_id=gid)
    with open(image_path, "rb") as fh:
        up = http.session().post(server["upload_url"],
                                 files={"photo": fh},
                                 timeout=config.HTTP_TIMEOUT).json()
    saved = _call("photos.saveWallPhoto", group_id=gid,
                  server=up["server"], photo=up["photo"], hash=up["hash"])
    p = saved[0]
    return f"photo{p['owner_id']}_{p['id']}"


def post(text: str, image_path: str | None = None) -> dict:
    if not is_enabled():
        return {"ok": False, "skipped": "vk_not_configured"}

    gid = str(config.VK_GROUP_ID).lstrip("-")
    message = _strip_html(text)
    if config.VK_FOOTER:
        message = f"{message}\n\n{config.VK_FOOTER}"

    if config.DRY_RUN:
        print(f"[DRY_RUN] VK wall.post -> club{gid}\nphoto: {image_path}\n"
              f"{message[:200]}…")
        return {"ok": True, "dry_run": True}

    attachments = ""
    if image_path:
        try:
            attachments = _upload_photo(image_path, gid)
        except Exception as exc:
            print("VK photo upload failed, posting text-only:", exc)

    resp = _call("wall.post", owner_id=f"-{gid}", from_group=1,
                 message=message, attachments=attachments)
    return {"ok": True, "post_id": resp.get("post_id")}
