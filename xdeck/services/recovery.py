"""予約投稿の失敗への対処(原因の分類 → 対処 → 間をあけて再実行)と、Discord への通知。"""
import asyncio
import subprocess
import time

from .. import platform_utils
from ..api_client import api, stop_browser
from ..config import BOARD_NAME, CHANNEL_IDS, ENT, FORTUNE, GALLERY_URL, NOTIFY_CHANNEL_ID
from . import discord_link, status

RETRY_DELAYS_MIN = [2, 10, 30]  # 失敗してから、1回目・2回目・3回目の再実行までの間隔(分)
RETRY_MAX = {"xdeck_down": 3, "network": 2, "session": 2, "other": 2}  # 種類ごとの最大再実行回数(直らない失敗を何度も繰り返さない)
RETRY_KINDS = tuple(RETRY_MAX)  # 自動で再実行する失敗の種類(timeout・permanent・posted は再実行しない)

# これらを含む失敗は、待っても直らないので再実行せず、すぐ通知する
PERMANENT = ("ゴミ箱", "削除されました", "重複", "duplicate", "凍結", "suspend", "ロック", "locked", "認証", "ログインが", "not logged", "unauthor", "文字数", "too long")
XDECK_DOWN = ("Connection refused", "Max retries", "ConnectionError", "403 Client Error", "Forbidden", "Failed to establish")
SESSION = ("ct0",)  # X のセッション用クッキーが読み込まれていない(Xdeck の再起動直後など)
NETWORK = ("メディアのアップロードに失敗", "ページ内でエラー", "Failed to fetch", "SecurityError", "timed out", "net::")

KIND_LABEL = {"xdeck_down": "Xdeck アプリに接続できない", "network": "アカウントのブラウザの通信エラー", "session": "アカウントのログイン情報(ct0)が読み込めていない", "other": "Xdeck 側の投稿エラー",
              "timeout": "Xdeck の処理が終わらない(投稿済みか不明)", "permanent": "アカウントや投稿内容の問題", "posted": "一部だけ投稿された可能性"}


def classify(err: str, timeout: bool = False, posted: bool = False) -> str:
    """失敗の原因を分類する。posted=ツイートIDが返っている(投稿が出た可能性あり)"""
    if timeout:
        return "timeout"  # 投稿できたか不明なので、二重投稿を避けて再実行しない
    if posted:
        return "posted"
    if any(k.lower() in err.lower() for k in PERMANENT):
        return "permanent"
    if any(k.lower() in err.lower() for k in XDECK_DOWN):
        return "xdeck_down"
    if any(k.lower() in err.lower() for k in SESSION):
        return "session"
    if any(k.lower() in err.lower() for k in NETWORK):
        return "network"
    return "other"


def _ensure_xdeck() -> str:
    """Xdeck アプリが応答しなければ起動して、応答するまで最大60秒待つ"""
    try:
        api("GET", "group/list", timeout=5)
        return "Xdeck は起動中"
    except Exception:  # noqa: BLE001
        pass
    platform_utils.launch_xdeck()
    for _ in range(20):
        time.sleep(3)
        try:
            api("GET", "group/list", timeout=5)
            return "Xdeck を起動し直した"
        except Exception:  # noqa: BLE001
            continue
    return "Xdeck を起動したが応答なし"


async def remedy(kind: str, profile_id: str) -> str:
    """原因に合わせた対処をして、やったことを返す"""
    if kind == "xdeck_down":
        return await asyncio.to_thread(_ensure_xdeck)
    if kind == "session":
        # ブラウザを止めて、プロフィール情報の取得で起動し直す(ログイン状態を読み込み直させる)
        ok = await asyncio.to_thread(stop_browser, profile_id)
        await asyncio.sleep(3)
        try:
            await asyncio.to_thread(api, "GET", "x/get", params={"profile_id": profile_id}, timeout=90)
        except Exception:  # noqa: BLE001
            pass
        return "ブラウザを再起動してログイン情報を読み込み直し" if ok else "ブラウザの再起動に失敗"
    # 通信エラー・原因不明: そのアカウントのブラウザを止める(次の操作で Xdeck が自動で起動し直す)
    return "アカウントのブラウザを再起動" if await asyncio.to_thread(stop_browser, profile_id) else "ブラウザの再起動に失敗"


def _channel_id() -> int | None:
    if NOTIFY_CHANNEL_ID:
        return NOTIFY_CHANNEL_ID
    m = discord_link.url_channel_id()
    if m or CHANNEL_IDS:
        return m or min(CHANNEL_IDS)
    # 監視チャンネルを絞っていないときは、Bot が書き込める最初のテキストチャンネル
    c = status._client
    for g in (c.guilds if c else []):
        ch = g.system_channel or next((x for x in g.text_channels if x.permissions_for(g.me).send_messages), None)
        if ch:
            return ch.id
    return None


_PENDING: list[str] = []  # 送れなかった通知(Discord がつながったら送る)


def _mac_notify(text: str) -> None:
    """Discord に送れないときの代わりに、デスクトップ通知を出す(macOS / Windows)"""
    platform_utils.desktop_notify(f"{BOARD_NAME}ボード", text)


async def _send(text: str) -> bool:
    c = status._client
    cid = _channel_id()
    if c is None or not c.is_ready() or not cid:
        return False
    try:
        ch = c.get_channel(cid) or await c.fetch_channel(cid)
        await ch.send(f"【{BOARD_NAME}ボード】{text}\n{GALLERY_URL}"[:1900])
        return True
    except Exception as e:  # noqa: BLE001
        print("notify error:", str(e)[:120])
        return False


async def notify(text: str) -> bool:
    """Discord に通知を送る。送れなければ Mac の通知を出し、Discord がつながったら送り直す。例外は出さない"""
    if await _send(text):
        return True
    print("notify: Discord に送れませんでした(後で送り直します):", text[:80])
    _PENDING.append(text)
    del _PENDING[:-20]
    await asyncio.to_thread(_mac_notify, text)
    return False


async def flush_pending() -> None:
    while _PENDING:
        if not await _send(_PENDING[0]):
            return
        _PENDING.pop(0)


# --- Xdeck アプリの見張り: 落ちていたら起動し直す(Xdeck 0.2.217 は DNS 処理でときどきクラッシュする) ---
_down_since: float | None = None


async def watchdog_loop() -> None:
    global _down_since
    while True:
        await asyncio.sleep(30)
        try:
            await flush_pending()
            try:
                await asyncio.to_thread(api, "GET", "group/list", timeout=5)
                if _down_since:
                    mins = (time.time() - _down_since) / 60
                    _down_since = None
                    if mins >= 3 and not ENT and not FORTUNE:
                        await notify(f"ℹ️ Xdeck が約{mins:.0f}分止まっていましたが、復旧しました。その間に失敗した予約は自動でやり直します")
                continue
            except Exception:  # noqa: BLE001
                pass
            if _down_since is None:
                _down_since = time.time()
                print("watchdog: Xdeck が応答しません。起動し直します")
            res = await asyncio.to_thread(_ensure_xdeck)
            print("watchdog:", res)
        except Exception as e:  # noqa: BLE001
            print("watchdog error:", e)
