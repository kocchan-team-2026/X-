"""予約投稿・即時投稿と、投稿履歴の集計。"""
import asyncio
import os
import shutil
from datetime import datetime, timedelta
from pathlib import Path

from ..api_client import JobTimeout, api, job_error, register_imp_alert, wait_job
from ..config import POSTS_DIR, SCHED_GRACE_MIN, STATE_DIR
from . import recovery
from .works import work_thread
from ..storage import append_posts_log, load_sched, read_posts_log, save_sched


SCHED_LOCK = asyncio.Lock()


def media_key(path: str) -> str:
    """添付の元ファイルを表す鍵 \"<投稿フォルダ>/<ファイル名>\"。posts/ の外(予約用コピーなど)は \"?/<ファイル名>\" """
    p = Path(path)
    try:
        return f"{p.resolve().relative_to(POSTS_DIR.resolve()).parts[0]}/{p.name}"
    except (ValueError, IndexError):
        return f"?/{p.name}"


async def send_post(work_id: str, profile_id: str, text: str, paths: list[str], src: list[str] | None = None) -> dict:
    payload = {"kind": "post", "profile_ids": [profile_id], "text": text}
    if paths:
        payload["media_paths"] = paths
    log = {"at": datetime.now().isoformat(timespec="seconds"), "work_id": work_id, "profile_id": profile_id,
           "text": text, "media": paths, "src": src or [media_key(x) for x in paths]}

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
    src = [media_key(x) for x in paths]  # 予約用コピーを作る前の、元の動画・画像
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
         "text": text, "media": kept, "src": src, "created": datetime.now().isoformat(timespec="seconds"), **(extra or {})}
    async with SCHED_LOCK:
        items = load_sched()
        items.append(e)
        save_sched(items)
    return e


def posted_media() -> dict[tuple[str, str], set[str]]:
    """{(work_id, profile_id): 使った動画・画像の鍵(media_key)}。投稿済み・予約済みの分。
    古い記録で元ファイルが分からないものは \"?/…#連番\" になる(パスで区別して本数を数える)"""
    out: dict[tuple[str, str], set[str]] = {}

    def add(work_id: str, profile_id: str, src: list[str] | None, media: list[str]) -> None:
        keys = out.setdefault((work_id, profile_id), set())
        # 元が不明な記録は、予約用コピーのパスで区別する(同じ投稿が予約と投稿ログの両方に出ても1件と数える)
        keys.update(src or [k if not k.startswith("?/") else f"{k}#{m}" for m, k in ((m, media_key(m)) for m in media)])

    for x in load_sched():
        if x["status"] in ("pending", "running", "done"):
            add(x["work_id"], x["profile_id"], x.get("src"), x.get("media", []))
    for e in read_posts_log():
        if e.get("event") == "response" and (e.get("response") or {}).get("code") == 0:
            add(e.get("work_id", ""), e.get("profile_id", ""), e.get("src"), e.get("media", []))
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
    failures: list[str] = []  # 自動再実行でも投稿できなかったもの(まとめて Discord に通知)
    missed = [d for d in due if d["status"] == "missed"]
    if missed:
        failures += [f"・{d['profile_name']} {d['at'][5:16].replace('T', ' ')} 「{d['text'][:25]}」 → 予約時刻に停止していたため見送り" for d in missed]
    for x in [d for d in due if d["status"] == "running"]:
        result: dict = {}
        job: dict = {}
        try:
            res = await send_post(x["work_id"], x["profile_id"], x["text"], x["media"], x.get("src"))
            if res.get("code") != 0:
                raise RuntimeError(res.get("msg") or str(res))
            jid = (res.get("data") or {}).get("job_id")
            job = await wait_job(jid)
            if job.get("failed", 0) > 0 or str(job.get("state")).lower() in ("failed", "error"):
                if job_error(job, "") == "":  # 終了直後は理由がまだ入っていないことがある。少し待って取り直す
                    await asyncio.sleep(2)
                    job = ((await asyncio.to_thread(api, "GET", "x/bulk/status", params={"job_id": jid, "id": jid})).get("data")) or job
                raise RuntimeError(job_error(job))
            label = ((job.get("steps") or [{}])[0].get("label") or "").replace("@", "")
            if label and job.get("tweet_id"):
                result["link"] = f"https://x.com/{label}/status/{job['tweet_id']}"
                result["imp_alert"] = await asyncio.to_thread(register_imp_alert, result["link"])
            status = "done"
            if job.get("tweet_id"):  # 続き(長文の残り)を、自分の投稿への返信として順に出す
                prev = str(job["tweet_id"])
                try:
                    from .followups import post_followup  # 循環import回避
                    for part in work_thread(x["work_id"]):
                        prev = await post_followup(x["profile_id"], prev, part) or prev
                except Exception as e2:  # noqa: BLE001
                    result["thread_error"] = str(e2)[:200]
                    failures.append(f"・{x['profile_name']} 「{x['text'][:25]}」 本文は投稿できましたが、続きのリプで失敗: {str(e2)[:120]}")
        except Exception as e:  # noqa: BLE001
            status, err = "failed", str(e)[:300]
            result["error"] = err
            kind = recovery.classify(err, timeout=isinstance(e, JobTimeout), posted=bool(job.get("tweet_id")))
            n = x.get("auto_retries", 0)
            log = list(x.get("retry_log", []))
            if kind in recovery.RETRY_KINDS and n < recovery.RETRY_MAX[kind]:
                # 原因に合わせて対処し、間をあけて(2分→10分→30分後)自動で再実行する。まだ投稿されていない失敗だけ
                did = await recovery.remedy(kind, x["profile_id"])
                wait = recovery.RETRY_DELAYS_MIN[n]
                log.append(f"{datetime.now():%H:%M} {recovery.KIND_LABEL[kind]} → {did}")
                status = "pending"
                result.pop("error")
                result.update(at=(datetime.now() + timedelta(minutes=wait)).isoformat(timespec="minutes"),
                              auto_retries=n + 1, last_error=err, retry_log=log)
                print(f"scheduler: {x['profile_name']} {kind}({err[:40]}) → {did}。{wait}分後にやり直します({n + 1}/{recovery.RETRY_MAX[kind]})")
            else:
                result["error_kind"] = kind
                tried = f"(自動再実行{n}回: " + " / ".join(log) + ")" if n else ""
                failures.append(f"・{x['profile_name']} {x['at'][5:16].replace('T', ' ')} 「{x['text'][:25]}」\n  原因: {recovery.KIND_LABEL[kind]} — {err[:120]}{tried}")
        async with SCHED_LOCK:
            items = load_sched()
            for y in items:
                if y["id"] == x["id"]:
                    y.update(result, status=status, finished=datetime.now().isoformat(timespec="seconds"))
            save_sched(items)
        if status == "done":
            shutil.rmtree(STATE_DIR / "_sched" / x["id"], ignore_errors=True)
    if failures:
        head = f"⚠️ 予約投稿を出せませんでした({len(failures)}件)。ボードの「予約履歴」で確認してください\n"
        await recovery.notify(head + "\n".join(failures[:8]) + (f"\n…ほか{len(failures) - 8}件" if len(failures) > 8 else ""))


async def recover_running() -> None:
    """前回、投稿処理の途中で停止した予約(running のまま残ったもの)を「失敗」にする。
    X に投稿済みかもしれないので自動では再投稿せず、確認してから「再試行」してもらう"""
    async with SCHED_LOCK:
        items = load_sched()
        n = 0
        for x in items:
            if x["status"] == "running":
                x.update(status="failed", finished=datetime.now().isoformat(timespec="seconds"),
                         error="投稿処理の途中でボードが停止しました。X に投稿済みか確認してから、必要なら再試行してください")
                n += 1
        if n:
            save_sched(items)
            print(f"scheduler: 処理中で止まっていた予約{n}件を「失敗」にしました")


async def scheduler_loop() -> None:
    try:
        await recover_running()
    except Exception as e:  # noqa: BLE001
        print("scheduler recover error:", e)
    while True:
        try:
            await run_due_posts()
        except Exception as e:  # noqa: BLE001
            print("scheduler error:", e)
        await asyncio.sleep(20)
