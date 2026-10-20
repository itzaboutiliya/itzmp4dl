"""iTZMP4DL Telegram bot. Run a single polling replica."""
import asyncio
import hmac
import logging
import os
import secrets
import tempfile
import time
from collections import OrderedDict
from pathlib import Path

from dotenv import load_dotenv
from telegram import InlineKeyboardButton as Button, InlineKeyboardMarkup as Keyboard
from telegram import MessageEntity, Update
from telegram.error import TelegramError
from telegram.ext import Application, CallbackQueryHandler, CommandHandler, MessageHandler, filters

from core import Access, links, validate_public_url
from media import download, inspect

load_dotenv()
log = logging.getLogger("itzmp4dl")


class Bot:
    def __init__(self):
        self.token = os.environ["BOT_TOKEN"]
        self.key = os.environ["ACCESS_KEY"]
        self.owners = {int(x.strip()) for x in os.environ["OWNER_IDS"].split(",") if x.strip()}
        if len(self.key) < 12 or not self.owners or not self.token:
            raise ValueError("Set BOT_TOKEN, OWNER_IDS and an ACCESS_KEY of at least 12 characters.")
        data = Path(os.getenv("DATA_DIR", "data"))
        data.mkdir(parents=True, exist_ok=True)
        self.access = Access(data / "access.sqlite3")
        self.duration = int(os.getenv("MAX_DURATION", "1800"))
        self.timeout = int(os.getenv("JOB_TIMEOUT", "600"))
        self.pending = OrderedDict()
        self.failures = OrderedDict()
        self.busy = False

    def identity(self, update):
        return update.effective_user.id if update.effective_chat.type == "private" else update.effective_chat.id

    def allowed(self, update):
        return update.effective_user.id in self.owners or self.access.allowed(self.identity(update))

    async def start(self, update, context):
        await update.effective_message.reply_text(
            "iTZMP4DL 🎬\nSend a website link to choose MP4 video or MP3 audio and quality.\n"
            "Activate once with /unlock YOUR_KEY. In groups, only an admin can activate.\n"
            "Ordinary text and Telegram links are ignored.\n"
            "Use /download URL in groups if Telegram privacy mode hides regular links.\n"
            "/id shows your user and chat IDs. /lock removes access for this chat."
        )

    async def admin(self, update, context):
        if update.effective_chat.type == "private":
            return True
        member = await context.bot.get_chat_member(update.effective_chat.id, update.effective_user.id)
        return member.status in {"creator", "administrator"}

    async def unlock(self, update, context):
        if not await self.admin(update, context):
            await update.effective_message.reply_text("Only a group admin can activate this group.")
            return
        try:
            await update.effective_message.delete()
        except TelegramError:
            pass
        uid = update.effective_user.id
        now = time.monotonic()
        count, until = self.failures.get(uid, (0, now))
        if now < until and count >= 5:
            await context.bot.send_message(update.effective_chat.id, "Too many attempts. Wait 15 minutes.")
            return
        if now >= until:
            count = 0
        if not hmac.compare_digest(" ".join(context.args).encode(), self.key.encode()):
            self.failures[uid] = (count + 1, until if count else now + 900)
            self.failures.move_to_end(uid)
            while len(self.failures) > 5000:
                self.failures.popitem(last=False)
            await context.bot.send_message(update.effective_chat.id, "Invalid access key. Use /unlock YOUR_KEY.")
            return
        self.failures.pop(uid, None)
        self.access.grant(self.identity(update))
        await context.bot.send_message(update.effective_chat.id, "Access activated. Send a website link.")

    async def identity_command(self, update, context):
        await update.effective_message.reply_text(f"User ID: {update.effective_user.id}\nChat ID: {update.effective_chat.id}")

    async def lock(self, update, context):
        if await self.admin(update, context):
            self.access.revoke(self.identity(update))
            await update.effective_message.reply_text("Access removed for this chat. Owners retain access.")

    async def owner(self, update, context):
        if update.effective_user.id not in self.owners or update.effective_chat.type != "private":
            return
        command = update.effective_message.text.split()[0].split("@")[0]
        if command == "/authorized":
            ids = self.access.all()
            text = "Authorized IDs:\n" + ("\n".join(map(str, ids)) or "None")
            for offset in range(0, len(text), 4000):
                await update.effective_message.reply_text(text[offset:offset + 4000])
            return
        try:
            identity = int(context.args[0])
        except (ValueError, IndexError):
            await update.effective_message.reply_text("Use /grant ID or /revoke ID.")
            return
        (self.access.grant if command == "/grant" else self.access.revoke)(identity)
        await update.effective_message.reply_text("Access updated.")

    def prune(self):
        now = time.monotonic()
        for key in list(self.pending):
            if self.pending[key]["expires"] < now:
                del self.pending[key]
        while len(self.pending) >= 200:
            self.pending.popitem(last=False)

    async def link(self, update, context):
        message = update.effective_message
        urls = links(message.text or message.caption)
        for entity, value in message.parse_entities([MessageEntity.TEXT_LINK]).items():
            urls.extend(links(entity.url))
        for entity, value in message.parse_caption_entities([MessageEntity.TEXT_LINK]).items():
            urls.extend(links(entity.url))
        if not urls:
            return
        if not self.allowed(update):
            await message.reply_text("Access required. Use /unlock YOUR_KEY; a group admin must activate groups.")
            return
        if self.busy:
            await message.reply_text("I'm processing another request. Please try again shortly.")
            return
        self.busy = True
        status = None
        try:
            status = await message.reply_text("Checking the link…")
            await asyncio.to_thread(validate_public_url, urls[0])
            with tempfile.TemporaryDirectory(prefix="itzmp4dl-") as directory:
                info = await inspect(urls[0], directory, self.duration)
            self.prune()
            key = secrets.token_hex(8)
            self.pending[key] = {"url": urls[0], "user": update.effective_user.id,
                                 "chat": update.effective_chat.id, "message": status.message_id,
                                 "expires": time.monotonic() + 900, **info}
            await status.edit_text(info["title"] + "\nChoose format:", reply_markup=Keyboard([
                [Button("🎬 MP4", callback_data=f"{key}:mp4"), Button("🎵 MP3", callback_data=f"{key}:mp3")],
                [Button("Cancel", callback_data=f"{key}:cancel")]]))
        except (ValueError, TimeoutError, OSError):
            if status:
                await status.edit_text("Couldn't read this video. The site may be unsupported, private, blocked, or too slow.")
        finally:
            self.busy = False

    async def choose(self, update, context):
        query = update.callback_query
        self.prune()
        parts = query.data.split(":")
        item = self.pending.get(parts[0])
        if not item or not query.message or item["chat"] != query.message.chat.id or item["message"] != query.message.message_id:
            await query.answer("This menu expired. Send the link again.", show_alert=True)
            return
        if item["user"] != query.from_user.id:
            await query.answer("Only the person who sent the link can use this menu.", show_alert=True)
            return
        if not self.allowed(update):
            await query.answer("Access has been revoked.", show_alert=True)
            return
        if len(parts) < 2:
            await query.answer()
            return
        kind = parts[1]
        if kind == "cancel":
            self.pending.pop(parts[0], None)
            await query.answer()
            await query.edit_message_text("Cancelled.")
            return
        if kind not in {"mp3", "mp4"}:
            await query.answer()
            return
        qualities = ["128", "192", "320"] if kind == "mp3" else [str(h) for h in item["heights"]] + ["best"]
        if len(parts) == 2:
            await query.answer()
            buttons = [Button((q + " kbps" if kind == "mp3" else q + "p" if q != "best" else "Best available"),
                              callback_data=f"{parts[0]}:{kind}:{q}") for q in qualities]
            rows = [buttons[i:i + 3] for i in range(0, len(buttons), 3)]
            rows.append([Button("Cancel", callback_data=f"{parts[0]}:cancel")])
            await query.edit_message_text(item["title"] + "\nChoose quality (MP4 uses up to the selected resolution):", reply_markup=Keyboard(rows))
            return
        if parts[2] not in qualities or self.busy:
            await query.answer("Busy. Try again shortly.", show_alert=True)
            return
        self.busy = True
        self.pending.pop(parts[0], None)
        try:
            await query.answer()
            await query.edit_message_text("Downloading and preparing your file…")
            await asyncio.to_thread(validate_public_url, item["url"])
            with tempfile.TemporaryDirectory(prefix="itzmp4dl-") as directory:
                path = await download(item["url"], kind, parts[2], directory, self.timeout, self.duration)
                await query.edit_message_text("Uploading to Telegram…")
                with path.open("rb") as file:
                    kwargs = dict(chat_id=item["chat"], caption=item["title"],
                                  message_thread_id=query.message.message_thread_id,
                                  read_timeout=120, write_timeout=180)
                    if kind == "mp3":
                        await context.bot.send_audio(audio=file, title=item["title"], **kwargs)
                    else:
                        await context.bot.send_video(video=file, supports_streaming=True, **kwargs)
            await query.edit_message_text("Done ✅ Send another website link whenever you're ready.")
        except ValueError as error:
            await query.edit_message_text(str(error))
        except TimeoutError:
            await query.edit_message_text("Download timed out. Try a shorter video or lower quality.")
        except (TelegramError, OSError):
            await query.edit_message_text("Download or upload failed. Please try again later.")
        finally:
            self.busy = False

    async def error(self, update, context):
        # Avoid logging tokens, URLs, keys, update contents or HTTP request traces.
        log.error("Handler failed: %s", type(context.error).__name__)

    def run(self):
        app = (Application.builder().token(self.token).concurrent_updates(16)
               .connect_timeout(30).read_timeout(60).write_timeout(180).build())
        for command, handler in [("start", self.start), ("help", self.start), ("unlock", self.unlock),
                                 ("id", self.identity_command), ("lock", self.lock),
                                 ("grant", self.owner), ("revoke", self.owner), ("authorized", self.owner),
                                 ("download", self.link)]:
            app.add_handler(CommandHandler(command, handler))
        app.add_handler(CallbackQueryHandler(self.choose))
        app.add_handler(MessageHandler((filters.TEXT | filters.CAPTION) & ~filters.COMMAND & filters.ChatType.GROUPS, self.link))
        app.add_handler(MessageHandler((filters.TEXT | filters.CAPTION) & ~filters.COMMAND & filters.ChatType.PRIVATE, self.link))
        app.add_handler(MessageHandler(filters.StatusUpdate.MIGRATE, self.migrate))
        app.add_error_handler(self.error)
        app.run_polling(allowed_updates=["message", "callback_query"], drop_pending_updates=True)

    async def migrate(self, update, context):
        message = update.effective_message
        old = message.migrate_from_chat_id or message.chat_id
        new = message.migrate_to_chat_id or message.chat_id
        if self.access.allowed(old):
            self.access.grant(new)
            self.access.revoke(old)


if __name__ == "__main__":
    logging.basicConfig(level=logging.WARNING)
    Bot().run()
