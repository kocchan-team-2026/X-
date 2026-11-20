"""サイドバーの「Discordを開く」ボタンのリンク。"""
from ..config import DISCORD_URL

_url = DISCORD_URL  # .env の DISCORD_URL があれば常にそれを使う


def get_url() -> str:
    return _url


def set_from_bot(guild_id: int | None, channel_id: int | None) -> None:
    """Bot が接続できたら、見ているチャンネル(なければサーバー)のURLを作る"""
    global _url
    if DISCORD_URL or not guild_id:
        return
    _url = f"https://discord.com/channels/{guild_id}" + (f"/{channel_id}" if channel_id else "")
