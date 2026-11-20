"""アカウントのアイコン取得(Xdeck の x/get から)。"""
import asyncio
import base64
from pathlib import Path
import re

import requests

from ..api_client import api
from ..config import STATE_DIR, group_ok


AV_LOCK = asyncio.Lock()


def av_dir() -> Path:
    d = STATE_DIR / "_avatars"
    d.mkdir(parents=True, exist_ok=True)
    return d


def av_ver(pid: str) -> int:
    """キャッシュ済みアイコンの更新時刻(なければ0)。画像URLのキャッシュ破棄に使う"""
    f = av_dir() / f"{pid}.jpg"
    return int(f.stat().st_mtime) if f.exists() else 0


async def fetch_avatars(force: bool = False) -> int:
    """Xdeck の x/get から各アカウントのアイコンを取得して保存する(1件ずつ・間隔を空ける)。
    force=False なら未取得のアカウントだけ。取得できた件数を返す"""
    if AV_LOCK.locked():
        return 0
    n = 0
    async with AV_LOCK:
        prof = (await asyncio.to_thread(api, "GET", "profile/list"))["data"]["list"]
        groups = (await asyncio.to_thread(api, "GET", "group/list"))["data"]["list"]
        gname = {g["group_id"]: g["name"] for g in groups}
        for x in prof:
            pid = x["profile_id"]
            if not group_ok(gname.get(x["group_id"], "")) or (not force and av_ver(pid)):
                continue
            try:
                info = (await asyncio.to_thread(api, "GET", "x/get", params={"profile_id": pid}))["data"]["profile"]
                m = re.match(r"data:image/[\w+.-]+;base64,(.+)", info.get("avatarDataUrl") or "", re.S)
                if m:
                    data = base64.b64decode(m.group(1))
                elif info.get("avatarUrl"):
                    data = (await asyncio.to_thread(requests.get, info["avatarUrl"], timeout=20)).content
                else:
                    continue
                await asyncio.to_thread((av_dir() / f"{pid}.jpg").write_bytes, data)
                n += 1
            except Exception as e:  # noqa: BLE001
                print(f"avatar: {pid} 取得失敗: {e}")
            await asyncio.sleep(1.0)
    return n
