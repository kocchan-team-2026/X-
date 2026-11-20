"""Discord Bot: X の投稿リンク・作品URLを検知して保存する。"""
import asyncio

import discord

from .config import (CHANNEL_IDS, ENT, ENT_CHANNELS, FOLLOWUP_ON, GALLERY_URL, POSTS_DIR, STATE_DIR,
                     URL_RE)
from .services.followups import followup_loop
from .services.scheduler import scheduler_loop
from .services.works import add_work_urls, already_saved, find_work_urls, save_tweet
from .web.app import start_web

intents = discord.Intents.default()
intents.message_content = True


class Bot(discord.Client):
    async def setup_hook(self):
        POSTS_DIR.mkdir(parents=True, exist_ok=True)
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        await start_web()
        self.sched_task = asyncio.create_task(scheduler_loop())
        if FOLLOWUP_ON:
            self.followup_task = asyncio.create_task(followup_loop())


client = Bot(intents=intents)


@client.event
async def on_ready():
    print(f"logged in as {client.user} / data dir: {POSTS_DIR.parent}")


@client.event
async def on_message(msg: discord.Message):
    if msg.author.bot:
        return
    in_thread = isinstance(msg.channel, discord.Thread)
    channel_id = msg.channel.parent_id if in_thread else msg.channel.id
    if CHANNEL_IDS and channel_id not in CHANNEL_IDS:
        return
    if not ENT and channel_id in ENT_CHANNELS:
        return
    m = URL_RE.search(msg.content)
    work_urls = [] if ENT else find_work_urls(msg.content)  # エンタメ用は作品URLなし
    # スレッド外の MyFans/FANZA だけの投稿は、紐づけ先の作品がないので無視
    if not m and not (work_urls and in_thread):
        return
    # 作品ID: スレッド内なら そのスレッドID。スレッド外なら このメッセージID。
    # (メッセージから作ったスレッドのIDは元メッセージIDと同じなので、最初の投稿と後続が同じ作品になる)
    work_id = str(msg.channel.id if in_thread else msg.id)
    try:
        notes = []
        if work_urls:
            new = await asyncio.to_thread(add_work_urls, work_id, work_urls)
            if new:
                notes.append("作品URLを登録: " + ", ".join(x["site"] for x in new))
        tw = None
        if m:
            if await asyncio.to_thread(already_saved, work_id, m.group(2)):
                notes.append("X投稿は保存済み")
            else:
                folder, videos, tw = await asyncio.to_thread(
                    save_tweet, m.group(1), m.group(2), work_id,
                    {"url": msg.jump_url, "thread": msg.channel.name if in_thread else None})
                notes.append("X投稿を保存")
        await msg.add_reaction("✅" if (tw or work_urls) else "♻️")
        summary = " / ".join(notes) or "変更なし"

        if in_thread:
            await msg.reply(f"{summary}\n{GALLERY_URL}", mention_author=False)
            return
        # 最初のリンク: スレッドを作り、以降のリンクをここに送ればこの作品にまとまる
        title = ((tw or {}).get("text") or m.group(1)).replace("\n", " ")[:50]
        try:
            thread = await msg.create_thread(name=title or "作品")
            await thread.send(f"{summary}\n{GALLERY_URL}\n同じ作品のXリンク・MyFans/FANZAのURLはこのスレッドに送ってください")
        except discord.Forbidden:
            await msg.reply(f"{summary}\n{GALLERY_URL}\n(スレッド作成の権限がないため、続きの追加はできません)",
                            mention_author=False)
    except Exception as e:  # noqa: BLE001
        await msg.add_reaction("❌")
        await msg.reply(f"保存失敗: {e}", mention_author=False)
