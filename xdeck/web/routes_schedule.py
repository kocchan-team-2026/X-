"""投稿・予約・一括予約・インプ達成通知のルート。"""
import asyncio
import os
import re
import shutil
from datetime import datetime, timedelta
from pathlib import Path

from aiohttp import web

from ..api_client import api, register_imp_alert
from ..config import BOARD_NAME, IMP_TARGET, STATE_DIR, group_ok
from ..services.bulk import BULK, run_bulk
from ..services.scheduler import SCHED_LOCK, add_sched, send_post
from ..storage import load_sched, save_sched
from .common import safe_path

routes = web.RouteTableDef()


async def build_post(body):
    """投稿内容を検証して (profile_id, text, paths) を返す"""
    text = (body.get("text") or "").strip()
    profile_id = body.get("profile_id") or ""
    files = body.get("files") or []
    if not profile_id or not text:
        raise web.HTTPBadRequest(text="profile_id and text are required")
    prof = (await asyncio.to_thread(api, "GET", "profile/list"))["data"]["list"]
    groups = (await asyncio.to_thread(api, "GET", "group/list"))["data"]["list"]
    gname = {g["group_id"]: g["name"] for g in groups}
    target = next((x for x in prof if x["profile_id"] == profile_id), None)
    if not target or not group_ok(gname.get(target["group_id"], "")):
        raise web.HTTPBadRequest(text=f"このアカウントは{BOARD_NAME}ボードからは投稿できません")
    paths = []
    for f in files:
        orig = safe_path(f["id"], f["name"])
        ed = orig.parent / "_edited" / orig.name
        # 「加工版を使う」指定のときは、事前に加工して残してある版だけを使う(未加工のまま黙って投稿しない)
        if f.get("edited"):
            if not ed.is_file():
                raise web.HTTPBadRequest(text=f"加工済みがありません: {orig.name}。先に「加工プレビュー」を実行してください")
            paths.append(str(ed))
        else:
            paths.append(str(orig))
    return profile_id, text, target["name"], paths


@routes.post("/api/post")
async def api_post(req):
    body = await req.json()
    profile_id, text, _name, paths = await build_post(body)
    res = await send_post(body.get("work_id", ""), profile_id, text, paths)
    return web.json_response(res)


@routes.post("/api/schedule")
async def api_sched_add(req):
    body = await req.json()
    try:
        at = datetime.fromisoformat(str(body.get("at", "")))
    except ValueError:
        raise web.HTTPBadRequest(text="日時の形式が正しくありません")
    if at <= datetime.now():
        raise web.HTTPBadRequest(text="予約日時は現在より後にしてください")
    profile_id, text, pname, paths = await build_post(body)
    e = await add_sched(body.get("work_id", ""), profile_id, pname, text, paths, at)
    return web.json_response(e)


@routes.get("/api/schedule")
async def api_sched_list(_):
    return web.json_response(sorted(load_sched(), key=lambda x: x["at"]))


@routes.post("/api/schedule/{sid}/retry")
async def api_sched_retry(req):
    """失敗・見送りになった予約を、すぐ(次の確認タイミングで)もう一度投稿する。sid=all で失敗分すべて"""
    sid = req.match_info["sid"]
    n = 0
    async with SCHED_LOCK:
        items = load_sched()
        for x in items:
            if (sid != "all" and x["id"] != sid) or x["status"] not in ("failed", "missed"):
                continue
            if any(not Path(p).exists() for p in x.get("media", [])):
                x["error"] = "添付ファイルが残っていないため再試行できません(削除して作り直してください)"
                continue
            for k in ("error", "finished", "link", "imp_alert", "auto_retries", "retry_log", "last_error", "error_kind"):
                x.pop(k, None)
            x["status"] = "pending"
            x["at"] = datetime.now().isoformat(timespec="minutes")
            x["retries"] = x.get("retries", 0) + 1
            n += 1
        save_sched(items)
    if not n and sid != "all":
        raise web.HTTPConflict(text="再試行できる状態ではありません")
    return web.json_response({"retried": n})


@routes.delete("/api/schedule/{sid}")
async def api_sched_del(req):
    sid = req.match_info["sid"]
    async with SCHED_LOCK:
        items = load_sched()
        hit = next((x for x in items if x["id"] == sid), None)
        if not hit:
            raise web.HTTPNotFound()
        if hit["status"] == "running":
            raise web.HTTPConflict(text="投稿処理中のため取り消せません")
        save_sched([x for x in items if x["id"] != sid])
    shutil.rmtree(STATE_DIR / "_sched" / sid, ignore_errors=True)
    return web.json_response({"ok": True})


@routes.post("/api/bulk")
async def api_bulk(req):
    b = await req.json()
    try:
        start = max(datetime.fromisoformat(str(b["start"])), datetime.now() + timedelta(minutes=2))
        end = datetime.fromisoformat(str(b["end"]))
        per = int(b.get("per", 1))
    except (KeyError, ValueError):
        raise web.HTTPBadRequest(text="入力が正しくありません")
    ids = [str(x) for x in b.get("profile_ids", [])]
    if not ids or not 1 <= per <= 20 or end <= start:
        raise web.HTTPBadRequest(text="アカウント・件数(1〜20)・時間帯(開始より後の終了)を確認してください")
    job = "bulk-" + datetime.now().strftime("%Y%m%d%H%M%S") + "-" + os.urandom(2).hex()
    BULK[job] = {"state": "running", "total": 0, "done": 0, "errors": [], "notes": []}
    asyncio.create_task(run_bulk(job, ids, start, end, per))
    return web.json_response({"job": job})


@routes.get("/api/bulk/{job}")
async def api_bulk_status(req):
    st = BULK.get(req.match_info["job"])
    if not st:
        raise web.HTTPNotFound()
    return web.json_response(st)


@routes.get("/api/job/{job}")
async def api_job(req):
    jid = req.match_info["job"]
    res = await asyncio.to_thread(api, "GET", "x/bulk/status", params={"job_id": jid, "id": jid})
    return web.json_response(res)


@routes.post("/api/imp_alert")
async def api_imp_alert(req):
    b = await req.json()
    url = str(b.get("url", ""))
    if not re.match(r"^https://x\.com/[^/]+/status/\d+$", url):
        raise web.HTTPBadRequest(text="invalid url")
    ok = await asyncio.to_thread(register_imp_alert, url)
    return web.json_response({"ok": ok, "target": IMP_TARGET})
