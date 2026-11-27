"""アカウント一覧・アイコン・インプ・シャドウバンのルート。"""
import asyncio
import os
from datetime import datetime

from aiohttp import web

from ..api_client import api, get_profiles
from ..config import group_ok
from ..services.avatars import av_dir, av_ver, fetch_avatars
from ..services.imps import IMP_JOBS, imp_load, last_tweets, run_imps
from ..services.scheduler import last_posts
from ..services.shadowban import SB_JOBS, run_shadowban, sb_load
from ..storage import load_sched

routes = web.RouteTableDef()


@routes.get("/api/avatar/{id}")
async def api_avatar(req):
    pid = req.match_info["id"]
    f = av_dir() / f"{pid}.jpg"
    if "/" in pid or ".." in pid or not f.exists():
        raise web.HTTPNotFound()
    return web.FileResponse(f, headers={"Cache-Control": "max-age=86400"})


@routes.post("/api/avatars/refresh")
async def api_avatars_refresh(_):
    asyncio.create_task(fetch_avatars(True))  # 数十秒かかるので裏で実行
    return web.json_response({"started": True})


@routes.get("/api/profiles")
async def api_profiles(_):
    asyncio.create_task(fetch_avatars())  # 未取得のアイコンだけ裏で取得(次回の読み込みで反映)
    prof = (await asyncio.to_thread(api, "GET", "profile/list"))["data"]["list"]
    groups = (await asyncio.to_thread(api, "GET", "group/list"))["data"]["list"]
    gname = {g["group_id"]: g["name"] for g in groups}
    last = await asyncio.to_thread(last_posts)
    sb = await asyncio.to_thread(sb_load)
    imps = await asyncio.to_thread(imp_load)
    lt = await asyncio.to_thread(last_tweets)
    nxt: dict[str, list[str]] = {}
    for x in await asyncio.to_thread(load_sched):
        if x["status"] in ("pending", "running"):
            nxt.setdefault(x["profile_id"], []).append(x["at"])
    return web.json_response([
        {"id": x["profile_id"], "name": x["name"], "group": gname.get(x["group_id"], ""),
         "last": last.get(x["profile_id"], ""), "sb": sb.get(x["profile_id"]),
         "imp": imps.get(x["profile_id"]), "has_post": x["profile_id"] in lt, "av": av_ver(x["profile_id"]),
         "next": min(nxt.get(x["profile_id"], [""])), "next_n": len(nxt.get(x["profile_id"], []))}
        for x in prof if group_ok(gname.get(x["group_id"], ""))])


@routes.post("/api/imps")
async def api_imps_start(req):
    b = await req.json()
    ids = [str(x) for x in b.get("profile_ids", [])]
    valid = {p["id"] for p in await asyncio.to_thread(get_profiles) if group_ok(p["group"])}
    lt = await asyncio.to_thread(last_tweets)
    targets = {i: lt[i] for i in ids if i in valid and i in lt}
    if not targets:
        raise web.HTTPBadRequest(text="投稿履歴のあるアカウントがありません")
    job = "imp-" + datetime.now().strftime("%H%M%S") + "-" + os.urandom(2).hex()
    IMP_JOBS[job] = {"state": "running", "total": len(targets), "done": 0}
    asyncio.create_task(run_imps(job, targets))
    return web.json_response({"job": job})


@routes.get("/api/imps/{job}")
async def api_imps_status(req):
    st = IMP_JOBS.get(req.match_info["job"])
    if not st:
        raise web.HTTPNotFound()
    return web.json_response(st)


@routes.post("/api/shadowban")
async def api_sb_start(req):
    b = await req.json()
    ids = [str(x) for x in b.get("profile_ids", [])]
    valid = {p["id"] for p in await asyncio.to_thread(get_profiles) if group_ok(p["group"])}
    ids = [i for i in ids if i in valid]
    if not ids:
        raise web.HTTPBadRequest(text="対象のアカウントがありません")
    job = "sb-" + datetime.now().strftime("%H%M%S") + "-" + os.urandom(2).hex()
    SB_JOBS[job] = {"state": "running", "total": len(ids), "done": 0}
    asyncio.create_task(run_shadowban(job, ids))  # 1件ずつ順番に(Xdeck側の負荷を避ける)
    return web.json_response({"job": job})


@routes.get("/api/shadowban/{job}")
async def api_sb_status(req):
    st = SB_JOBS.get(req.match_info["job"])
    if not st:
        raise web.HTTPNotFound()
    return web.json_response(st)


@routes.get("/api/dm/replies")
async def api_dm_replies(_):
    """DM の新しい返信(新しい順)。DM 返信の確認が対象にしているアカウントだけ"""
    from ..services.dm import recent_replies
    return web.json_response({"replies": await asyncio.to_thread(recent_replies)})


@routes.get("/api/dm/settings")
async def api_dm_settings(_):
    """「アダルト2」画面用: 一通目の自動送信・返信確認の ON/OFF、本日の送信数、対象アカウント、最近の返信"""
    from ..config import DM_CHECK_MIN, DM_FIRST_MIN
    from ..services import dm
    prof = await asyncio.to_thread(dm.dm_profiles)
    return web.json_response({**dm.get_settings(), "today": dm.sent_today(), "first_min": DM_FIRST_MIN, "check_min": DM_CHECK_MIN,
                              "accounts": [p["name"] for p in prof], "replies": await asyncio.to_thread(dm.recent_replies, 20)})


@routes.post("/api/dm/settings")
async def api_dm_settings_set(req):
    from ..services import dm
    b = await req.json()
    return web.json_response(dm.set_settings(**{k: b[k] for k in ("first_on", "reply_on") if k in b}))
