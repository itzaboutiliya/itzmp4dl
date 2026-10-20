import os
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from core import Access, links, validate_public_url


class CoreTests(unittest.TestCase):
    def test_text_and_telegram_links_are_ignored(self):
        for text in ["hello there", "please download this", "https://t.me/example", "https://telegram.me/example", "https://sub.telegram.org/test", "tg://resolve?domain=test"]:
            self.assertEqual(links(text), [])

    def test_mixed_links(self):
        self.assertEqual(links("watch https://example.com/video.mp4 and https://t.me/test"), ["https://example.com/video.mp4"])
        self.assertEqual(links("https://t.me.evil.example/video"), ["https://t.me.evil.example/video"])

    def test_access_survives_restart_and_revocation(self):
        with tempfile.TemporaryDirectory() as directory:
            path = directory + "/access.db"
            first = Access(path)
            first.grant(-123)
            first.db.close()
            second = Access(path)
            self.assertTrue(second.allowed(-123))
            self.assertFalse(second.allowed(123))
            second.revoke(-123)
            self.assertFalse(second.allowed(-123))
            second.db.close()

    def test_local_network_rejected(self):
        with patch("core.socket.getaddrinfo", return_value=[(2, 1, 6, "", ("127.0.0.1", 443))]):
            with self.assertRaises(ValueError):
                validate_public_url("https://example.com/video")


class HandlerTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        from bot import Bot
        self.directory = tempfile.TemporaryDirectory()
        with patch.dict(os.environ, {"BOT_TOKEN": "123:test", "ACCESS_KEY": "long-test-key-123", "OWNER_IDS": "1", "DATA_DIR": self.directory.name}):
            self.bot = Bot()

    async def asyncTearDown(self):
        self.bot.access.db.close()
        self.directory.cleanup()

    def update(self, text, uid=2, chat_type="private"):
        message = SimpleNamespace(text=text, caption=None, parse_entities=lambda *a: {},
                                  parse_caption_entities=lambda *a: {}, reply_text=AsyncMock(), delete=AsyncMock())
        return SimpleNamespace(effective_message=message, effective_user=SimpleNamespace(id=uid),
                               effective_chat=SimpleNamespace(id=uid if chat_type == "private" else -10, type=chat_type))

    async def test_silent_messages(self):
        for text in ["hello", "https://t.me/test", "hello https://telegram.org/test"]:
            update = self.update(text)
            await self.bot.link(update, SimpleNamespace())
            update.effective_message.reply_text.assert_not_awaited()

    async def test_unapproved_link_requires_access(self):
        update = self.update("https://example.com/video.mp4")
        await self.bot.link(update, SimpleNamespace())
        update.effective_message.reply_text.assert_awaited_once()

    async def test_nonadmin_cannot_unlock_group(self):
        update = self.update("/unlock long-test-key-123", chat_type="group")
        context = SimpleNamespace(args=["long-test-key-123"], bot=SimpleNamespace(get_chat_member=AsyncMock(return_value=SimpleNamespace(status="member"))))
        await self.bot.unlock(update, context)
        self.assertFalse(self.bot.access.allowed(-10))

    async def test_admin_unlocks_only_group(self):
        update = self.update("/unlock long-test-key-123", chat_type="group")
        context = SimpleNamespace(args=["long-test-key-123"], bot=SimpleNamespace(
            get_chat_member=AsyncMock(return_value=SimpleNamespace(status="administrator")), send_message=AsyncMock()))
        await self.bot.unlock(update, context)
        self.assertTrue(self.bot.access.allowed(-10))
        self.assertFalse(self.bot.access.allowed(2))

    async def test_application_registers_without_network(self):
        with patch("telegram.ext.Application.run_polling") as polling:
            self.bot.run()
            polling.assert_called_once()

    async def test_other_user_cannot_use_menu(self):
        update = self.update("", uid=3)
        update.callback_query = SimpleNamespace(data="abc:mp3:192", from_user=SimpleNamespace(id=3),
            message=SimpleNamespace(chat=SimpleNamespace(id=3), message_id=5), answer=AsyncMock())
        self.bot.pending["abc"] = {"user": 2, "chat": 3, "message": 5, "expires": float("inf")}
        await self.bot.choose(update, SimpleNamespace())
        update.callback_query.answer.assert_awaited_once_with("Only the person who sent the link can use this menu.", show_alert=True)


if __name__ == "__main__":
    unittest.main()
