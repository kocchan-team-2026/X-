"""ボードが開いたアカウントのブラウザを、使い終わったら閉じる(メモリを使いすぎないように)。

Xdeck は、API でアカウントを操作すると、そのアカウントのブラウザを自動で開き、開いたままにする。
そこで api() がアカウントに触れるたびに記録し、
- 触れる前に閉じていたもの(=ボードが開いたもの)だけを「ボードの持ち物」とし、
- 最後に使ってから IDLE_SEC 秒たち、Xdeck で実行中のジョブにも入っていなければ、閉じる。
もともと開いていたブラウザ(自分で開いて使っているもの)は閉じない。
"""
import asyncio
import threading
import time

import requests

from .config import XDECK_TOKEN, XDECK_URL

IDLE_SEC = 90          # 最後に使ってからこの秒数たったら閉じる
SWEEP_SEC = 30         # 閉じてよいか確かめる間隔
_NO_BROWSER = ("browser/", "cookie/", "profile/", "group/", "imp-alerts/", "x/bulk/status", "x/bulk/jobs", "x/bulk/kinds",
               "extension/", "auth/", "system/", "dock/", "panel/", "audio/", "adblock/", "templates/", "ai/", "local-schedule/",
               "schedule/", "x/credentials", "x/totp")  # ブラウザを開かない(開く必要のない)呼び出し

_lock = threading.Lock()
_owned: set[str] = set()          # ボードが開いたアカウント
_last_used: dict[str, float] = {}  # アカウント -> 最後に使った時刻
_open_cache: tuple[float, set[str]] = (0.0, set())


def _raw(method: str, path: str, **kw) -> dict:
    r = requests.request(method, f"{XDECK_URL}/{path}", headers={"X-Api-Token": XDECK_TOKEN}, timeout=kw.pop("timeout", 15), **kw)
    r.raise_for_status()
    return r.json()


def _open_now(max_age: float = 5.0) -> set[str]:
    global _open_cache
    if time.time() - _open_cache[0] > max_age:
        try:
            lst = _raw("GET", "browser/list")["data"]["list"]
            _open_cache = (time.time(), {x["profileId"] for x in lst})
        except Exception as e:  # noqa: BLE001
            print("browsers: 一覧の取得に失敗:", str(e)[:80])
    return _open_cache[1]


def note_use(path: str, kw: dict) -> None:
    """api() から呼ばれる。このリクエストで触れるアカウントを記録する(まだ開いていなければ、ボードの持ち物にする)"""
    if path.startswith(_NO_BROWSER) and path != "x/bulk":
        return
    pids = []
    p = (kw.get("params") or {}).get("profile_id")
    if p:
        pids.append(p)
    pids += (kw.get("json") or {}).get("profile_ids") or []
    if not pids:
        return
    with _lock:
        for pid in pids:
            if pid not in _owned and pid not in _open_now():
                _owned.add(pid)  # 閉じていたものを、これから開く
            _last_used[pid] = time.time()


def _running_profiles() -> set[str]:
    jobs = _raw("GET", "x/bulk/jobs")["data"].get("jobs") or []
    return {pid for j in jobs if str(j.get("state")).lower() in ("running", "queued", "pending", "waiting") for pid in j.get("profile_ids") or []}


def sweep() -> list[str]:
    """使い終わったボードの持ち物のブラウザを閉じる。閉じたアカウントのIDを返す"""
    with _lock:
        idle = [p for p in _owned if time.time() - _last_used.get(p, 0) > IDLE_SEC]
    if not idle:
        return []
    try:
        busy = _running_profiles()
    except Exception as e:  # noqa: BLE001
        print("browsers: ジョブ一覧の取得に失敗(今回は閉じません):", str(e)[:80])
        return []
    closed = []
    for pid in idle:
        if pid in busy:
            continue
        try:
            _raw("GET", "browser/stop", params={"profile_id": pid}, timeout=30)
            closed.append(pid)
        except Exception as e:  # noqa: BLE001
            print("browsers: 閉じるのに失敗:", pid[:8], str(e)[:80])
    with _lock:
        _owned.difference_update(closed)
        _last_used.update({p: _last_used.get(p, 0) for p in closed})
    return closed


async def sweep_loop() -> None:
    while True:
        await asyncio.sleep(SWEEP_SEC)
        try:
            n = await asyncio.to_thread(sweep)
            if n:
                print(f"browsers: {len(n)}件のアカウントのブラウザを閉じました")
        except Exception as e:  # noqa: BLE001
            print("browsers error:", e)
