"""Isolated downloader process with a hard timeout and disk budget."""
import asyncio
import json
import os
import signal
import sys
from pathlib import Path

MAX_BYTES = 49_000_000
DISK_BUDGET = 180_000_000


async def run(args, directory, timeout):
    output = Path(directory) / "process.log"
    with output.open("wb") as log:
        process = await asyncio.create_subprocess_exec(
            sys.executable, "-m", "yt_dlp", *args,
            stdout=log, stderr=asyncio.subprocess.DEVNULL,
            start_new_session=(os.name != "nt"),
        )
        try:
            async with asyncio.timeout(timeout):
                while process.returncode is None:
                    await asyncio.sleep(.5)
                    size = sum(p.stat().st_size for p in Path(directory).rglob("*") if p.is_file())
                    if size > DISK_BUDGET:
                        raise ValueError("Download exceeded the temporary storage limit. Choose lower quality.")
                if process.returncode:
                    raise ValueError("This website could not provide that format. Try another quality or link.")
        finally:
            if os.name != "nt":
                # Also stop ffmpeg descendants, including after the parent exits.
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
            elif process.returncode is None:
                process.kill()
            await process.wait()
    return output.read_text(encoding="utf-8")


def base():
    return ["--ignore-config", "--no-playlist", "--no-warnings", "--quiet",
            "--socket-timeout", "20", "--retries", "2", "--fragment-retries", "2",
            "--js-runtimes", "node"]


async def inspect(url, directory, max_duration):
    data = json.loads(await run(base() + ["--dump-single-json", "--skip-download", "--", url], directory, 60))
    if data.get("is_live") or data.get("_type") in {"playlist", "multi_video"}:
        raise ValueError("Live streams and playlists are not supported. Send one video link.")
    if (data.get("duration") or 0) > max_duration:
        raise ValueError(f"This video exceeds the {max_duration // 60}-minute limit.")
    heights = sorted({int(f["height"]) for f in data.get("formats", []) if f.get("height") and f.get("vcodec") != "none"})
    return {"title": str(data.get("title") or "Download")[:180], "heights": heights[-12:]}


async def download(url, kind, quality, directory, timeout, max_duration):
    args = base() + ["--max-filesize", str(MAX_BYTES), "--match-filters",
                    f"!is_live & duration <=? {max_duration}",
                    "--output", str(Path(directory) / "media.%(ext)s")]
    if kind == "mp3":
        args += ["--format", "bestaudio/best", "--extract-audio", "--audio-format", "mp3", "--audio-quality", quality]
    else:
        bound = f"[height<={quality}]" if quality != "best" else ""
        args += ["--format", f"bv*{bound}[ext=mp4]+ba[ext=m4a]/b{bound}[ext=mp4]/bv*{bound}+ba/b{bound}",
                 "--merge-output-format", "mp4", "--recode-video", "mp4"]
    await run(args + ["--", url], directory, timeout)
    path = Path(directory) / f"media.{kind}"
    if not path.is_file():
        raise ValueError("No file was produced; it may exceed Telegram's upload limit. Try lower quality.")
    if path.stat().st_size > MAX_BYTES:
        raise ValueError("The result is too large for Telegram. Choose lower quality or a shorter video.")
    return path
