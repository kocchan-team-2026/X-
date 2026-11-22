"""接続状態(Discord Bot / Xdeck)。ダッシュボード右上の緑・赤の表示に使う。"""
import asyncio
import math
import time

from ..api_client import api

_client = None
_dropped = False  # Discord の切断を検知してから、再接続するまで True
_xd = {"at": 0.0, "ok": False, "msg": "未確認"}


def set_client(c) -> None:
    global _client
    _client = c


def discord_dropped() -> None:
    global _dropped
    _dropped = True


def discord_connected() -> None:
    global _dropped
    _dropped = False


def discord_state() -> dict:
    c = _client
    if c is None or not c.is_ready():
        return {"ok": False, "msg": "接続中、または未接続です"}
    if c.is_closed() or _dropped or not math.isfinite(c.latency):
        return {"ok": False, "msg": "切断されています(自動で再接続を試みます)"}
    return {"ok": True, "msg": f"接続中({c.latency * 1000:.0f}ms)"}


async def xdeck_state() -> dict:
    """Xdeck API への疎通確認。負荷を避けるため10秒は結果を使い回す"""
    if time.time() - _xd["at"] < 10:
        return {"ok": _xd["ok"], "msg": _xd["msg"]}
    try:
        await asyncio.to_thread(api, "GET", "group/list", timeout=5)
        _xd.update(ok=True, msg="接続中")
    except Exception as e:  # noqa: BLE001
        _xd.update(ok=False, msg=f"Xdeckに接続できません(Xdeckアプリが起動しているか確認): {str(e)[:60]}")
    _xd["at"] = time.time()
    return {"ok": _xd["ok"], "msg": _xd["msg"]}
