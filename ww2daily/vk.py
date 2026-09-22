"""Cross-post to a VK community you own.

Two kinds of token work here, and the module adapts to whichever it is given:

* a COMMUNITY token («Управление → Работа с API → Ключи доступа», rights
  «Стена» + «Фотографии»). Always obtainable in a minute, but VK does not let it
  upload wall photos (photos.getWallUploadServer → error 27) or create polls
  (polls.create is user-only). In this mode a post carries the photo as a link
  card to its Commons page, and the quiz goes out as a text post that invites
  answers in the comments;
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
import urllib.parse

from . import config, http

API = "https://api.vk.com/method/"
COMMONS_FILE = "https://commons.wikimedia.org/wiki/"

# VK error codes.
ERR_GROUP_AUTH = 27      # "method is unavailable with group auth"
ERR_USER_AUTH = 5        # bad / revoked user token


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


_token_kind: str | None = None


def token_kind() -> str:
    """'user' or 'group', probed once per process."""
    global _token_kind
    if _token_kind is None:
        try:
            _call("users.get")
            _token_kind = "user"
        except VKError as exc:
            _token_kind = "group" if exc.code == ERR_GROUP_AUTH else "user"
    return _token_kind


def _with_footer(text: str) -> str:
    message = _strip_html(text)
    if config.VK_FOOTER:
        message = f"{message}\n\n{config.VK_FOOTER}"
    return message


def commons_page_url(title: str | None) -> str | None:
    """Public page of a Commons file — VK renders it as a link card with the
    picture, which is how a community token still shows the photo."""
    if not title:
        return None
    return COMMONS_FILE + urllib.parse.quote(title.replace(" ", "_"), safe=":/()")


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


def post(text: str, image_path: str | None = None,
         link: str | None = None) -> dict:
    """Publish on the community wall.

    `image_path` is uploaded as a real photo when the token allows it;
    otherwise (community token, or a failed upload) `link` — the Commons page
    of the picture — is attached instead, so the post still shows the frame."""
    if not is_enabled():
        return {"ok": False, "skipped": "vk_not_configured"}

    gid = group_id()
    message = _with_footer(text)

    if config.DRY_RUN:
        print(f"[DRY_RUN] VK wall.post -> club{gid}\nphoto: {image_path}\n"
              f"link: {link}\n{message[:200]}…")
        return {"ok": True, "dry_run": True}

    attachments = ""
    if image_path and token_kind() == "user":
        try:
            attachments = _upload_photo(image_path, gid)
        except Exception as exc:
            print("VK photo upload failed, falling back to a link card:", exc)
    if not attachments and link:
        attachments = link

    resp = _call("wall.post", owner_id=f"-{gid}", from_group=1,
                 message=message, attachments=attachments)
    return {"ok": True, "post_id": resp.get("post_id"),
            "photo": "uploaded" if attachments.startswith("photo")
            else "link" if attachments else "none"}


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
        me = _call("users.get")[0]
        kind = "user"
        print(f"token kind: USER — {me.get('first_name')} {me.get('last_name')} "
              f"(id{me.get('id')}); photos and polls fully supported")
    except VKError as exc:
        if exc.code != ERR_GROUP_AUTH:
            return [f"the token does not work ({exc})"]
        kind = "group"
        print("token kind: COMMUNITY — posts go out with a link card instead of "
              "an uploaded photo, quizzes as text posts (comments), answers "
              "revealed by comment")

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
