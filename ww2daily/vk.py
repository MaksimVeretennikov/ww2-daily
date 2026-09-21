"""Cross-post to a VK community you own.

Posting to a community wall with a photo needs a USER access token (scopes
wall,photos,groups,offline). VK community tokens cannot upload wall photos
(photos.getWallUploadServer fails with error 27; the messages-album workaround
uploads but renders text-only on the wall), and polls.create is user-only too —
so everything here runs on the owner's user token. The image is uploaded
directly from the local file — no proxy needed.

Polls: VK has no quiz mode (no correct answer, no explanation), so a quiz goes
out as a regular poll attached to a wall post, and the answer is revealed the
next day as a comment from the community under that post (see post_poll and
reveal_answer).
"""

import json
import re
import time

from . import config, http

API = "https://api.vk.com/method/"


class VKError(RuntimeError):
    def __init__(self, code: int, msg: str):
        super().__init__(f"VK error {code}: {msg}")
        self.code = code


def is_enabled() -> bool:
    return bool(config.VK_ACCESS_TOKEN and config.VK_GROUP_ID)


def group_id() -> str:
    """Positive numeric community id, however it was written in the env."""
    return str(config.VK_GROUP_ID).strip().lstrip("-").removeprefix("club") \
        .removeprefix("public")


def _strip_html(s: str) -> str:
    return re.sub(r"<[^>]+>", "", s or "").strip()


def _call(method: str, **params) -> dict | list:
    params.setdefault("access_token", config.VK_ACCESS_TOKEN)
    params.setdefault("v", config.VK_API_VERSION)
    resp = http.session().post(API + method, data=params,
                               timeout=config.HTTP_TIMEOUT)
    resp.raise_for_status()
    data = resp.json()
    if "error" in data:
        err = data["error"]
        raise VKError(err.get("error_code", 0), err.get("error_msg", "?"))
    return data["response"]


def _with_footer(text: str) -> str:
    message = _strip_html(text)
    if config.VK_FOOTER:
        message = f"{message}\n\n{config.VK_FOOTER}"
    return message


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

    gid = group_id()
    message = _with_footer(text)

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


# --- polls -------------------------------------------------------------------

def post_poll(question: str, options: list[str], intro: str = "") -> dict:
    """Create an anonymous poll on the community and publish it on the wall.

    Returns {"ok", "post_id", "poll_id"}; the caller records them so the
    answer can be revealed under the same post tomorrow."""
    if not is_enabled():
        return {"ok": False, "skipped": "vk_not_configured"}

    gid = group_id()
    message = _with_footer(intro)

    if config.DRY_RUN:
        print(f"[DRY_RUN] VK polls.create + wall.post -> club{gid}\n"
              f"Q: {question}\n  " + "\n  ".join(options) + f"\n{message}")
        return {"ok": True, "dry_run": True}

    params = dict(
        question=question,
        add_answers=json.dumps(options, ensure_ascii=False),
        owner_id=f"-{gid}",
        is_anonymous=1,
        disable_unvote=1,
    )
    if config.VK_POLL_HOURS > 0:
        params["end_date"] = int(time.time()) + config.VK_POLL_HOURS * 3600
    try:
        poll = _call("polls.create", **params)
    except VKError as exc:
        if "end_date" not in params:
            raise
        print("VK refused the poll end_date, creating an open-ended poll:", exc)
        params.pop("end_date")
        poll = _call("polls.create", **params)

    attachment = f"poll{poll['owner_id']}_{poll['id']}"
    resp = _call("wall.post", owner_id=f"-{gid}", from_group=1,
                 message=message, attachments=attachment)
    return {"ok": True, "post_id": resp.get("post_id"), "poll_id": poll["id"]}


def reveal_answer(post_id: int, text: str) -> dict:
    """Comment under a poll post, from the community, with the correct answer."""
    if not is_enabled():
        return {"ok": False, "skipped": "vk_not_configured"}
    gid = group_id()
    if config.DRY_RUN:
        print(f"[DRY_RUN] VK wall.createComment -> club{gid} post {post_id}\n"
              f"{text}")
        return {"ok": True, "dry_run": True}
    resp = _call("wall.createComment", owner_id=f"-{gid}", post_id=post_id,
                 from_group=gid, message=_strip_html(text))
    return {"ok": True, "comment_id": resp.get("comment_id")}


# --- diagnostics -------------------------------------------------------------

def check() -> list[str]:
    """Verify the token and the community without posting anything.

    Returns a list of human-readable problems (empty = all good)."""
    problems: list[str] = []
    if not config.VK_ACCESS_TOKEN:
        problems.append("VK_ACCESS_TOKEN is not set")
    if not config.VK_GROUP_ID:
        problems.append("VK_GROUP_ID is not set")
    if problems:
        return problems

    gid = group_id()
    try:
        me = _call("users.get")[0]
        print(f"token owner: {me.get('first_name')} {me.get('last_name')} "
              f"(id{me.get('id')})")
    except VKError as exc:
        return [f"the token is not a working USER token ({exc}); a community "
                "token cannot upload photos or create polls"]

    try:
        perms = int(_call("account.getAppPermissions", user_id=me["id"]))
    except VKError as exc:
        perms = -1
        print("could not read scopes:", exc)
    if perms >= 0:
        for bit, name in ((4, "photos"), (8192, "wall"), (262144, "groups"),
                          (65536, "offline")):
            if not perms & bit:
                problems.append(f"the token lacks the '{name}' scope")

    try:
        groups = _call("groups.getById", group_id=gid, fields="is_admin,name")
        g = groups["groups"][0] if isinstance(groups, dict) else groups[0]
        print(f"community: {g.get('name')} (club{g.get('id')})")
        if not g.get("is_admin"):
            problems.append("the token owner is not an admin of the community")
    except VKError as exc:
        problems.append(f"community club{gid} could not be read ({exc})")

    try:
        _call("photos.getWallUploadServer", group_id=gid)
    except VKError as exc:
        problems.append(f"wall photo upload is unavailable ({exc})")
    return problems
