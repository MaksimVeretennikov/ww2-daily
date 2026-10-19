import contextlib
import importlib.util
import io
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch


SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
spec = importlib.util.spec_from_file_location("publish", SCRIPTS / "publish.py")
publish = importlib.util.module_from_spec(spec)
spec.loader.exec_module(publish)


class PublicationMemoryTest(unittest.TestCase):
    def test_telegram_only_skips_all_crossposting_and_rss(self):
        draft = {"telegram_caption": "<b>19 октября 1941</b>", "image_index": 0,
                 "post_x": "English post"}
        candidate = {"index": 0, "pageid": 123, "title": "File:Archive.jpg"}
        with contextlib.ExitStack() as stack:
            stack.enter_context(patch.object(sys, "argv", ["publish.py"]))
            stack.enter_context(patch.object(publish, "_load", side_effect=[draft, [candidate]]))
            stack.enter_context(patch.object(publish.state, "load", return_value={"posts": []}))
            stack.enter_context(patch.object(publish, "_resolve_image", return_value="photo.jpg"))
            sent = stack.enter_context(patch.object(publish.telegram, "send_photo"))
            stack.enter_context(patch.object(publish.config, "TELEGRAM_ONLY", True))
            stack.enter_context(patch.object(publish.config, "DRY_RUN", False))
            stack.enter_context(patch.object(publish.config, "VK_ACCESS_TOKEN", "configured"))
            stack.enter_context(patch.object(publish.config, "VK_GROUP_ID", "123"))
            stack.enter_context(patch.object(publish.config, "BUFFER_WEBHOOK_URL", "configured"))
            for module, method in ((publish.buffer, "post"), (publish.twitter, "post"),
                                   (publish.vk, "token_kind"), (publish.vk, "post"),
                                   (publish.feed, "stage_image"), (publish.feed, "write")):
                stack.enter_context(patch.object(module, method, side_effect=AssertionError(method)))
            saved = stack.enter_context(patch.object(publish.state, "append"))
            stack.enter_context(contextlib.redirect_stdout(io.StringIO()))
            publish.main()

        sent.assert_called_once()
        saved.assert_called_once()
        self.assertNotIn("feed_image", saved.call_args.args[0])
        self.assertEqual(saved.call_args.args[0]["image_pageid"], 123)

    def test_telegram_only_poll_skips_vk_and_answer_reveal(self):
        import json

        poll_spec = importlib.util.spec_from_file_location("publish_poll", SCRIPTS / "publish_poll.py")
        poll = importlib.util.module_from_spec(poll_spec)
        poll_spec.loader.exec_module(poll)
        draft = {"ww2_date": "1941-10-19", "question": "Вопрос?",
                 "options": ["Первый", "Второй", "Третий", "Четвёртый"], "correct_index": 0}
        history = {"polls": [{"date": "2026-10-18", "vk_post_id": 123}]}
        with tempfile.TemporaryDirectory() as directory, contextlib.ExitStack() as stack:
            path = Path(directory) / "poll.json"
            path.write_text(json.dumps(draft), encoding="utf-8")
            stack.enter_context(patch.object(sys, "argv", ["publish_poll.py", "--poll", str(path)]))
            stack.enter_context(patch.object(poll.config, "TELEGRAM_ONLY", True))
            stack.enter_context(patch.object(poll.config, "DRY_RUN", False))
            stack.enter_context(patch.object(poll.config, "VK_ACCESS_TOKEN", "configured"))
            stack.enter_context(patch.object(poll.config, "VK_GROUP_ID", "123"))
            stack.enter_context(patch.object(poll.state, "load_polls", return_value=history))
            stack.enter_context(patch.object(poll.state, "load", return_value={"posts": []}))
            sent = stack.enter_context(patch.object(poll.telegram, "send_poll"))
            saved = stack.enter_context(patch.object(poll.state, "append_poll"))
            stack.enter_context(patch.object(poll.vk, "reveal_answer", side_effect=AssertionError("VK reveal")))
            stack.enter_context(patch.object(poll.vk, "post_poll", side_effect=AssertionError("VK poll")))
            stack.enter_context(contextlib.redirect_stdout(io.StringIO()))
            poll.main()

        sent.assert_called_once()
        saved.assert_called_once()

    def test_vk_token_probe_failure_preserves_sent_telegram_post(self):
        draft = {"telegram_caption": "<b>19 октября 1941</b>", "image_index": 0}
        candidate = {"index": 0, "pageid": 123, "title": "File:Archive.jpg"}
        with contextlib.ExitStack() as stack:
            stack.enter_context(patch.object(sys, "argv", ["publish.py"]))
            stack.enter_context(patch.object(publish, "_load", side_effect=[draft, [candidate]]))
            stack.enter_context(patch.object(publish.state, "load", return_value={"posts": []}))
            stack.enter_context(patch.object(publish, "_resolve_image", return_value="photo.jpg"))
            sent = stack.enter_context(patch.object(publish.telegram, "send_photo"))
            stack.enter_context(patch.object(publish.vk, "is_enabled", return_value=True))
            stack.enter_context(patch.object(publish.vk, "token_kind", side_effect=OSError("VK unavailable")))
            stack.enter_context(patch.object(publish.config, "DRY_RUN", False))
            stack.enter_context(patch.object(publish.config, "TELEGRAM_ONLY", False))
            stack.enter_context(patch.object(publish.feed, "stage_image", return_value="img/archive.jpg"))
            stack.enter_context(patch.object(publish.feed, "write"))
            saved = stack.enter_context(patch.object(publish.state, "append", return_value={"posts": []}))
            stack.enter_context(contextlib.redirect_stdout(io.StringIO()))
            publish.main()

        sent.assert_called_once_with("photo.jpg", draft["telegram_caption"])
        saved.assert_called_once()
        record = saved.call_args.args[0]
        self.assertEqual(record["image_pageid"], 123)
        self.assertEqual(record["telegram_caption"], draft["telegram_caption"])
        self.assertEqual(record["feed_image"], "img/archive.jpg")


if __name__ == "__main__":
    unittest.main()
