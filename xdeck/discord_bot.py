"""Discord Bot: X の投稿リンク・作品URLを検知して保存する。"""
import asyncio
from datetime import timedelta

import discord

from .config import (CHANNEL_IDS, ENT, ENT_CHANNELS, FOLLOWUP_ON, GALLERY_URL, POSTS_DIR, STATE_DIR,
                     URL_RE)
from .services import discord_link, recovery, status
from .services.followups import followup_loop
from .services.routine import routine_loop
from .services.scheduler import scheduler_loop
from .services import fanza
from .services.works import add_work_urls, work_affiliate, set_affiliate, already_saved, find_work_urls, save_tweet
from .web.app import start_web

intents = discord.Intents.default()
intents.message_content = True


class Bot(discord.Client):
    async def setup_hook(self):
        POSTS_DIR.mkdir(parents=True, exist_ok=True)
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        status.set_client(self)
        await start_web()
        self.sched_task = asyncio.create_task(scheduler_loop())
        self.watchdog_task = asyncio.create_task(recovery.watchdog_loop())
        self.routine_task = asyncio.create_task(routine_loop())
        if FOLLOWUP_ON:
            self.followup_task = asyncio.create_task(followup_loop())


client = Bot(intents=intents)


@client.event
async def on_disconnect():
    status.discord_dropped()


@client.event
async def on_resumed():
    status.discord_connected()


@client.event
async def on_ready():
    status.discord_connected()
    print(f"logged in as {client.user} / data dir: {POSTS_DIR.parent}")
    # 設定したチャンネルのうち、Bot から見えるものがあればそのチャンネルを、なければ最初のサーバーを開く
    ch = next((c for c in (client.get_channel(i) for i in sorted(CHANNEL_IDS)) if c), None)
    guild = ch.guild if ch else (client.guilds[0] if client.guilds else None)
    discord_link.set_from_bot(guild.id if guild else None, ch.id if ch else None)
    global _retried
    if not _retried:  # 再接続のたびには走らせない
        _retried = True
        asyncio.create_task(retry_unsaved())


RETRY_HOURS = 72  # 起動時に、この時間以内の失敗・未処理のリンクを拾い直す
_retried = False


@client.event
async def on_message(msg: discord.Message):
    if msg.author.bot:
        return
    await process(msg)


async def process(msg: discord.Message, notify: bool = True) -> bool:
    """メッセージ内の X リンク・作品URLを保存する。対象外なら何もしない。保存に失敗したら False
    (notify=False は拾い直し用: 失敗してもスレッドに返信しない)"""
    in_thread = isinstance(msg.channel, discord.Thread)
    channel_id = msg.channel.parent_id if in_thread else msg.channel.id
    if CHANNEL_IDS and channel_id not in CHANNEL_IDS:
        return True
    if not ENT and channel_id in ENT_CHANNELS:
        return True
    m = URL_RE.search(msg.content)
    work_urls = [] if ENT else find_work_urls(msg.content)  # エンタメ用は作品URLなし
    # スレッド外の MyFans/FANZA だけの投稿は、紐づけ先の作品がないので無視
    if not m and not (work_urls and in_thread):
        return True
    # 作品ID: スレッド内なら そのスレッドID。スレッド外なら このメッセージID。
    # (メッセージから作ったスレッドのIDは元メッセージIDと同じなので、最初の投稿と後続が同じ作品になる)
    work_id = str(msg.channel.id if in_thread else msg.id)
    try:
        notes = []
        if work_urls:
            new = await asyncio.to_thread(add_work_urls, work_id, work_urls)
            if new:
                notes.append("作品URLを登録: " + ", ".join(x["site"] for x in new))
            # FANZA のURLが入ったとき、アフィリエイトリンクが未登録なら自動で作る(登録済みは上書きしない)
            fz = next((x["url"] for x in work_urls if x["site"] == "FANZA"), "")
            if fz and fanza.enabled() and not await asyncio.to_thread(work_affiliate, work_id):
                link = await asyncio.to_thread(fanza.make_link, fz)
                if link:
                    await asyncio.to_thread(set_affiliate, work_id, link)
                    notes.append("アフィリエイトリンクを自動作成")
                else:
                    notes.append("アフィリエイトリンクを作れませんでした(手動で登録してください)")
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
            return True
        # 最初のリンク: スレッドを作り、以降のリンクをここに送ればこの作品にまとまる
        title = ((tw or {}).get("text") or m.group(1)).replace("\n", " ")[:50]
        try:
            thread = await msg.create_thread(name=title or "作品")
            await thread.send(f"{summary}\n{GALLERY_URL}\n同じ作品のXリンク・MyFans/FANZAのURLはこのスレッドに送ってください")
        except discord.Forbidden:
            await msg.reply(f"{summary}\n{GALLERY_URL}\n(スレッド作成の権限がないため、続きの追加はできません)",
                            mention_author=False)
        except discord.HTTPException as e:
            if e.code != 160004:
                raise
            # このメッセージには既にスレッドがある(拾い直しなど)。そこに知らせる
            th = msg.channel.get_thread(msg.id) or await client.fetch_channel(msg.id)
            await th.send(f"{summary}\n{GALLERY_URL}")
        return True
    except Exception as e:  # noqa: BLE001
        await msg.add_reaction("❌")
        if notify:
            await msg.reply(f"保存失敗: {e}", mention_author=False)
        print(f"save failed: {msg.jump_url}: {e}", flush=True)
        return False


async def retry_unsaved(hours: int = RETRY_HOURS) -> None:
    """直近の履歴から、保存に失敗(❌のまま)・未処理の X リンク/作品URLを探して保存し直す(Bot停止中・ディスク不足などの取りこぼし用)"""
    cutoff = discord.utils.utcnow() - timedelta(hours=hours)
    boxes: list = []
    for g in client.guilds:
        for ch in g.text_channels:
            if (CHANNEL_IDS and ch.id not in CHANNEL_IDS) or (not ENT and ch.id in ENT_CHANNELS):
                continue
            boxes.append(ch)
            boxes += ch.threads
            try:
                boxes += [t async for t in ch.archived_threads(limit=50) if (t.archive_timestamp or cutoff) >= cutoff]
            except discord.HTTPException:
                pass
    ok = bad = 0
    for box in boxes:
        try:
            async for msg in box.history(after=cutoff, oldest_first=True, limit=None):
                mine = {str(r.emoji) for r in msg.reactions if r.me}
                if msg.author.bot or mine & {"✅", "♻️"}:
                    continue
                if not (URL_RE.search(msg.content) or (not ENT and find_work_urls(msg.content))):
                    continue
                if "❌" in mine:
                    await msg.remove_reaction("❌", client.user)
                if await process(msg, notify=False):
                    ok += 1
                    print(f"retry ok: {msg.jump_url}", flush=True)
                else:
                    bad += 1
        except discord.HTTPException as e:
            print(f"retry: {box} を読めませんでした: {e}", flush=True)
    print(f"retry: 保存し直し {ok}件 / 失敗 {bad}件", flush=True)
