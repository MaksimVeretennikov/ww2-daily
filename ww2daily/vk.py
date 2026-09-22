"""Cross-post to a VK community you own.

Two kinds of token work here, and the module adapts to whichever it is given:

* a COMMUNITY token («Управление → Работа с API → Ключи доступа», rights
  «Стена» + «Фотографии»). Always obtainable in a minute, but VK gives it no
  way to put a photo on the wall (every upload server but stories answers
  error 27, and a messages-album photo renders as text in the feed), so posts
  go out text-only, and the quiz — which it cannot create as a poll either —
  goes out as a text post that invites answers in the comments;
* a USER token (scopes wall,photos,groups,offline — via your own VK ID app;
  the old trick of borrowing another app's client_id is blocked by VK now).
  Full mode: real photo attachments and real polls.

VK has no quiz mode in either case, so the previous quiz's answer is revealed
the next day as a comment from the community under that post
(see post_poll / reveal_answer).
"""

import json
import re
import time

from . import config, http

API = "https://api.vk.com/method/"

# VK error codes.
ERR_GROUP_AUTH = 27      # "method is unavailable with group auth"
ERR_USER_AUTH = 5        # bad / revoked user token


class VKError(RuntimeError):
    def __init__(self, code: int, msg: str):
        super().__init__(f"VK error {code}: {msg}")
        self.code = code


def is_enabled() -> bool:
    return bool(config.VK_ACCESS_TOKEN and config.VK_GROUP_ID)


def posts_enabled() -> bool:
    """Whether the daily post and rubrics go to VK through the API.

    Default ("auto"): only with a user token. A community key would post them
    text-only, and the RSS import delivers the same posts with the photo."""
    if not is_enabled():
        return False
    if config.VK_MIRROR == "all":
        return True
    if config.VK_MIRROR == "polls":
        return False
    return token_kind() == "user"


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


_token_kind: str | None = None


def token_kind() -> str:
    """'user' or 'group', probed once per process."""
    global _token_kind
    if _token_kind is None:
        # A community key answers users.get with an empty list (or error 27
        # on some methods); a user token returns its owner.
        try:
            _token_kind = "user" if _call("users.get") else "group"
        except VKError as exc:
            _token_kind = "group" if exc.code == ERR_GROUP_AUTH else "user"
    return _token_kind


def _with_footer(text: str) -> str:
    message = _strip_html(text)
    if config.VK_FOOTER:
        message = f"{message}\n\n{config.VK_FOOTER}"
    return message




def _upload_photo(image_path: str, gid: str) -> str:
    """Upload a local file and return its `photo<owner>_<id>` attachment.

    User token only. Verified against the API with a community key: every
    upload server but stories answers error 27, and a photo pushed through
    the messages upload server attaches but renders as plain text in the
    feed — so a community key gets no photo at all rather than a phantom."""
    if token_kind() != "user":
        raise VKError(ERR_GROUP_AUTH, "a community key cannot upload wall photos")
    server = _call("photos.getWallUploadServer", group_id=gid)
    with open(image_path, "rb") as fh:
        up = http.session().post(server["upload_url"],
                                 files={"photo": ("photo.jpg", fh, "image/jpeg")},
                                 timeout=config.HTTP_TIMEOUT).json()
    if not up.get("photo") or up["photo"] == "[]":
        raise RuntimeError(f"VK upload server rejected the file: {up}")
    saved = _call("photos.saveWallPhoto", group_id=gid, server=up["server"],
                  photo=up["photo"], hash=up["hash"])
    p = saved[0]
    return f"photo{p['owner_id']}_{p['id']}"


def post(text: str, image_path: str | None = None) -> dict:
    """Publish on the community wall, with `image_path` uploaded as a photo.

    A failed upload degrades to a text post rather than losing the post: VK
    refuses link cards to Wikimedia (link_photo_sizing_rule), so there is no
    cheaper way to show the frame."""
    if not is_enabled():
        return {"ok": False, "skipped": "vk_not_configured"}

    gid = group_id()
    message = _with_footer(text)

    if config.DRY_RUN:
        print(f"[DRY_RUN] VK wall.post -> club{gid}\nphoto: {image_path}\n"
              f"{message[:200]}…")
        return {"ok": True, "dry_run": True}

    attachments = ""
    if image_path and token_kind() == "user":
        try:
            attachments = _upload_photo(image_path, gid)
        except Exception as exc:
            print("VK photo upload failed, posting text-only:", exc)
    elif image_path:
        print("VK: community key cannot attach photos — posting text-only.")

    resp = _call("wall.post", owner_id=f"-{gid}", from_group=1,
                 message=message, attachments=attachments)
    return {"ok": True, "post_id": resp.get("post_id"),
            "photo": "uploaded" if attachments else "none"}


# --- polls -------------------------------------------------------------------

LETTERS = "АБВГДЕЖЗИК"


def _quiz_as_text(question: str, options: list[str]) -> str:
    lines = [question, ""]
    lines += [f"{LETTERS[i]}) {o}" for i, o in enumerate(options)]
    lines += ["", "Напишите букву ответа в комментариях. "
                  "Верный ответ и пояснение — завтра в комментариях."]
    return "\n".join(lines)


def post_poll(question: str, options: list[str], intro: str = "") -> dict:
    """Publish the daily quiz on the community wall.

    With a user token: an anonymous VK poll attached to a wall post. With a
    community token (polls.create is user-only): the same quiz as a text post
    inviting answers in the comments. Returns {"ok", "post_id", "poll_id"};
    the caller records them so the answer can be revealed tomorrow."""
    if not is_enabled():
        return {"ok": False, "skipped": "vk_not_configured"}

    gid = group_id()

    if config.DRY_RUN:
        print(f"[DRY_RUN] VK poll -> club{gid}\nQ: {question}\n  "
              + "\n  ".join(options) + f"\n{_with_footer(intro)}")
        return {"ok": True, "dry_run": True}

    if token_kind() == "group":
        resp = _call("wall.post", owner_id=f"-{gid}", from_group=1,
                     message=_with_footer(_quiz_as_text(question, options)))
        return {"ok": True, "post_id": resp.get("post_id"), "poll_id": None,
                "mode": "text"}

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
                 message=_with_footer(intro), attachments=attachment)
    return {"ok": True, "post_id": resp.get("post_id"), "poll_id": poll["id"],
            "mode": "poll"}


def reveal_answer(post_id: int, text: str) -> dict:
    """Comment under a quiz post, from the community, with the correct answer.
    Works with both token kinds."""
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
        users = _call("users.get")
    except VKError as exc:
        if exc.code != ERR_GROUP_AUTH:
            return [f"the token does not work ({exc})"]
        users = []
    if users:
        kind = "user"
        me = users[0]
        print(f"token kind: USER — {me.get('first_name')} {me.get('last_name')} "
              f"(id{me.get('id')}); photos and polls fully supported")
    else:
        kind = "group"
        print("token kind: COMMUNITY — posts go out TEXT-ONLY (VK lets no "
              "community key put a photo on the wall), quizzes as text posts "
              "(answers in comments), answers revealed by comment")

    if kind == "user":
        try:
            perms = int(_call("account.getAppPermissions", user_id=me["id"]))
            for bit, name in ((4, "photos"), (8192, "wall"), (262144, "groups"),
                              (65536, "offline")):
                if not perms & bit:
                    problems.append(f"the token lacks the '{name}' scope")
        except VKError as exc:
            print("could not read scopes:", exc)
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
    else:
        try:
            perms = _call("groups.getTokenPermissions")
            names = {p.get("name") for p in perms.get("permissions", [])}
            print("community key rights:", ", ".join(sorted(names)) or "none")
            for need in ("wall", "photos"):
                if need not in names:
                    problems.append(f"the community key lacks the '{need}' right "
                                    "— recreate it with «Стена» and «Фотографии»")
        except VKError as exc:
            print("could not read the key's rights:", exc)
        try:
            groups = _call("groups.getById", group_id=gid, fields="name")
            g = groups["groups"][0] if isinstance(groups, dict) else groups[0]
            print(f"community: {g.get('name')} (club{g.get('id')})")
        except VKError as exc:
            problems.append(f"community club{gid} could not be read ({exc}) — "
                            "is the key issued by this very community?")
    return problems
