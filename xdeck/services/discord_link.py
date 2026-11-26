"""サイドバーの「Discordを開く」ボタンのリンク。"""
from ..config import DISCORD_URL

_channel: int | None = None  # Bot が見ているチャンネルID(通知の送り先の候補)
_url = DISCORD_URL  # .env の DISCORD_URL があれば常にそれを使う


def get_url() -> str:
    return _url


def url_channel_id() -> int | None:
    return _channel


def set_from_bot(guild_id: int | None, channel_id: int | None) -> None:
    """Bot が接続できたら、見ているチャンネル(なければサーバー)のURLを作る"""
    global _url, _channel
    _channel = channel_id
    if DISCORD_URL or not guild_id:
        return
    _url = f"https://discord.com/channels/{guild_id}" + (f"/{channel_id}" if channel_id else "")
