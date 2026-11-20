"""予約投稿・即時投稿と、投稿履歴の集計。"""
import asyncio
import os
import shutil
from datetime import datetime, timedelta
from pathlib import Path

from ..api_client import api, register_imp_alert
from ..config import SCHED_GRACE_MIN, STATE_DIR
from ..storage import append_posts_log, load_sched, read_posts_log, save_sched


SCHED_LOCK = asyncio.Lock()


async def send_post(work_id: str, profile_id: str, text: str, paths: list[str]) -> dict:
    payload = {"kind": "post", "profile_ids": [profile_id], "text": text}
    if paths:
        payload["media_paths"] = paths
    log = {"at": datetime.now().isoformat(timespec="seconds"), "work_id": work_id, "profile_id": profile_id,
           "text": text, "media": paths}

    def write_log(extra):
        append_posts_log({**log, **extra})

    write_log({"event": "request"})  # 先に記録(失敗しても何を送ったか残る)
    # Xdeck は投稿完了まで応答を返さないことがある(30秒前後)ので長めに待つ
    res = await asyncio.to_thread(api, "POST", "x/bulk", json=payload, timeout=300)
    write_log({"event": "response", "response": res})
    return res


async def add_sched(work_id: str, profile_id: str, pname: str, text: str, paths: list[str], at: datetime,
                    extra: dict | None = None) -> dict:
    sid = datetime.now().strftime("%Y%m%d%H%M%S") + "-" + os.urandom(3).hex()
    # 加工済み動画は後から作り直されても変わらないよう、予約時点のコピーを保持する
    snap = STATE_DIR / "_sched" / sid
    snap.mkdir(parents=True, exist_ok=True)
    kept = []
    for src in paths:
        dst = snap / Path(src).name
        await asyncio.to_thread(shutil.copy2, src, dst)
        kept.append(str(dst))
    e = {"id": sid, "at": at.isoformat(timespec="minutes"), "status": "pending",
         "work_id": work_id, "profile_id": profile_id, "profile_name": pname,
         "text": text, "media": kept, "created": datetime.now().isoformat(timespec="seconds"), **(extra or {})}
    async with SCHED_LOCK:
        items = load_sched()
        items.append(e)
        save_sched(items)
    return e


def posted_pairs() -> set[tuple[str, str]]:
    """(work_id, profile_id): すでに投稿済み、または予約済みの組み合わせ"""
    out = {(x["work_id"], x["profile_id"]) for x in load_sched() if x["status"] in ("pending", "running", "done")}
    for e in read_posts_log():
        if e.get("event") == "response" and (e.get("response") or {}).get("code") == 0:
            out.add((e.get("work_id", ""), e.get("profile_id", "")))
    return out


def last_posts() -> dict[str, str]:
    """アカウントごとの前回投稿日時(このボードから投稿した分)。ISO文字列"""
    out: dict[str, str] = {}

    def upd(pid: str, at: str) -> None:
        if pid and at and at > out.get(pid, ""):
            out[pid] = at

    for e in read_posts_log():
        if e.get("event") == "response" and (e.get("response") or {}).get("code") == 0:
            upd(e.get("profile_id", ""), e.get("at", ""))
    for x in load_sched():
        if x["status"] == "done":
            upd(x["profile_id"], x.get("finished") or x["at"])
    return out


async def run_due_posts() -> None:
    now = datetime.now()
    async with SCHED_LOCK:
        items = load_sched()
        due = [x for x in items if x["status"] == "pending" and datetime.fromisoformat(x["at"]) <= now]
        for x in due:
            if now - datetime.fromisoformat(x["at"]) > timedelta(minutes=SCHED_GRACE_MIN):
                x["status"] = "missed"
            else:
                x["status"] = "running"
        if due:
            save_sched(items)
    for x in [d for d in due if d["status"] == "running"]:
        result: dict = {}
        try:
            res = await send_post(x["work_id"], x["profile_id"], x["text"], x["media"])
            if res.get("code") != 0:
                raise RuntimeError(res.get("msg") or str(res))
            jid = (res.get("data") or {}).get("job_id")
            job = {}
            for _ in range(30):
                job = ((await asyncio.to_thread(api, "GET", "x/bulk/status", params={"job_id": jid, "id": jid})).get("data")) or {}
                if str(job.get("state")).lower() in ("done", "failed", "error", "finished", "completed"):
                    break
                await asyncio.sleep(2)
            if job.get("failed", 0) > 0 or str(job.get("state")).lower() in ("failed", "error"):
                raise RuntimeError(job.get("error") or "Xdeck 側で投稿に失敗しました")
            label = ((job.get("steps") or [{}])[0].get("label") or "").replace("@", "")
            if label and job.get("tweet_id"):
                result["link"] = f"https://x.com/{label}/status/{job['tweet_id']}"
                result["imp_alert"] = await asyncio.to_thread(register_imp_alert, result["link"])
            status = "done"
        except Exception as e:  # noqa: BLE001
            status, result["error"] = "failed", str(e)[:300]
        async with SCHED_LOCK:
            items = load_sched()
            for y in items:
                if y["id"] == x["id"]:
                    y.update(result, status=status, finished=datetime.now().isoformat(timespec="seconds"))
            save_sched(items)
        if status == "done":
            shutil.rmtree(STATE_DIR / "_sched" / x["id"], ignore_errors=True)


async def scheduler_loop() -> None:
    while True:
        try:
            await run_due_posts()
        except Exception as e:  # noqa: BLE001
            print("scheduler error:", e)
        await asyncio.sleep(20)
