"""アカウントごとの最新投稿のインプ数取得。"""
import asyncio
import json
import re
from datetime import datetime

from ..api_client import api
from ..config import STATE_DIR
from ..storage import load_sched, read_posts_log


IMP_FILE = lambda: STATE_DIR / "_imps.json"  # noqa: E731
IMP_JOBS: dict[str, dict] = {}
IMP_LOCK = asyncio.Lock()


def imp_load() -> dict:
    f = IMP_FILE()
    return json.loads(f.read_text(encoding="utf-8")) if f.exists() else {}


def last_tweets() -> dict[str, dict]:
    """アカウントごとの最新投稿(このボードから投稿した分)。{profile_id: {tweet_id, at, link}}"""
    out: dict[str, dict] = {}

    def upd(pid: str, at: str, tid: str, link: str = "") -> None:
        if pid and tid and at and at > out.get(pid, {}).get("at", ""):
            out[pid] = {"tweet_id": str(tid), "at": at, "link": link}

    for e in read_posts_log():
        r = e.get("response") or {}
        if e.get("event") == "response" and r.get("code") == 0:
            upd(e.get("profile_id", ""), e.get("at", ""), (r.get("data") or {}).get("tweet_id", ""))
    for x in load_sched():
        if x["status"] == "done" and x.get("link"):
            m = re.search(r"/status/(\d+)", x["link"])
            if m:
                upd(x["profile_id"], x.get("finished") or x["at"], m.group(1), x["link"])
    return out


async def run_imps(job: str, targets: dict[str, dict]) -> None:
    st = IMP_JOBS[job]
    sem = asyncio.Semaphore(4)  # 同時4件まで(各アカウントの通信経路が遅いため並列化)

    async def one(pid: str, t: dict) -> None:
        async with sem:
            try:
                res = await asyncio.to_thread(api, "GET", "x/tweet", params={"profile_id": pid, "tweet": t["tweet_id"]}, timeout=90)
                if res.get("code") != 0:
                    raise RuntimeError(res.get("msg") or "failed")
                d = res["data"]
                c = d.get("counts") or {}
                rec = {"tweet_id": t["tweet_id"], "posted_at": t["at"], "views": c.get("views"), "likes": c.get("favorites"),
                       "retweets": c.get("retweets"), "replies": c.get("replies"), "bookmarks": c.get("bookmarks"),
                       "screen_name": (d.get("author") or {}).get("screenName", ""),
                       "fetched_at": datetime.now().isoformat(timespec="seconds")}
            except Exception as e:  # noqa: BLE001
                rec = {"tweet_id": t["tweet_id"], "posted_at": t["at"], "views": None, "error": str(e)[:120],
                       "fetched_at": datetime.now().isoformat(timespec="seconds")}
        async with IMP_LOCK:
            d0 = imp_load()
            d0[pid] = rec
            IMP_FILE().write_text(json.dumps(d0, ensure_ascii=False, indent=1), encoding="utf-8")
        st["done"] += 1

    try:
        await asyncio.gather(*(one(p, t) for p, t in targets.items()))
        st["state"] = "finished"
    except Exception as e:  # noqa: BLE001
        st["state"] = "error"
        st["error"] = str(e)[:200]
