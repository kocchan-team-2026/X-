"""一括予約(作品を重み付きランダムで選び、時間をばらして予約)。"""
import asyncio
import random
import re
from datetime import datetime, timedelta

from ..api_client import get_profiles
from ..config import POSTS_DIR, group_ok
from ..media import edit_video
from ..rewrite import rewrite_text
from .scheduler import add_sched, posted_pairs
from .works import list_items


BULK: dict[str, dict] = {}


def pick_media(work: dict):
    """作品から添付を1つ選ぶ。動画があれば動画をランダムで1本、なければ画像(最大4枚)"""
    vids = [(p["id"], v) for p in work["posts"] for v in p["videos"]]
    if vids:
        pid, v = random.choice(vids)
        return next(p for p in work["posts"] if p["id"] == pid), [(pid, v, "v")]
    for p in work["posts"]:
        if p["images"]:
            return p, [(p["id"], i, "i") for i in p["images"][:4]]
    return None, []


async def prep_one(work: dict, profile: dict, at: datetime, batch: str) -> dict:
    """1件分: 本文リライト + 動画加工 + 予約登録"""
    post, media = pick_media(work)
    if not media:
        raise RuntimeError("動画も画像もない作品です")
    base = re.sub(r"\s*https?://\S+", "", post["text"]).strip()
    text = base
    if base:
        try:
            cands = await asyncio.to_thread(rewrite_text, base)
            text = random.choice(cands) if cands else base
        except Exception:  # noqa: BLE001
            text = base  # リライトに失敗したら元の文のまま
    if not text:
        raise RuntimeError("本文が空です")
    paths = []
    for pid, name, kind in media:
        src = POSTS_DIR / pid / name
        if kind == "v":
            dest = src.parent / "_edited" / src.name
            u = random.uniform
            lo, hi = 0.1, 0.5
            async with EDIT_LOCK:  # 同じ動画の _edited を同時に書かないように
                await asyncio.to_thread(edit_video, src, dest, 0.02, round(u(0.02, 0.08), 3), round(u(1.05, 1.15), 3),
                                        1.15, round(u(lo, hi), 2), round(u(lo, hi), 2))
                kept = await add_sched(work["work_id"], profile["id"], profile["name"], text, [str(dest)], at,
                                       {"bulk": batch})
            return kept
        paths.append(str(src))
    return await add_sched(work["work_id"], profile["id"], profile["name"], text, paths, at, {"bulk": batch})


EDIT_LOCK = asyncio.Lock()


def work_weight(w: dict) -> float:
    """作品の選ばれやすさ(0=自動選択から外す / 1=標準 / 2=2倍選ばれやすい …)"""
    try:
        return max(0.0, min(10.0, float(w.get("weight", 1))))
    except (TypeError, ValueError):
        return 1.0


async def run_bulk(job: str, profile_ids: list[str], start: datetime, end: datetime, per: int) -> None:
    st = BULK[job]
    try:
        profs = {p["id"]: p for p in await asyncio.to_thread(get_profiles)}
        chosen = [profs[i] for i in profile_ids if i in profs and group_ok(profs[i]["group"])]
        works = [w for w in await asyncio.to_thread(list_items) if pick_media(w)[1]]
        used = posted_pairs()
        usage: dict[str, int] = {w["work_id"]: 0 for w in works}
        plan = []
        for pr in chosen:
            elig = [w for w in works if (w["work_id"], pr["id"]) not in used and work_weight(w) > 0]
            if len({work_weight(w) for w in elig}) > 1:
                # 作品ごとの「選ばれやすさ」が違うときは、重みに比例した確率で選ぶ(重複なし)
                # 重み付きランダム抽出: キー = 乱数^(1/重み) の大きい順(Efraimidis–Spirakis)
                elig.sort(key=lambda w: random.random() ** (1 / work_weight(w)), reverse=True)
            else:
                random.shuffle(elig)
                elig.sort(key=lambda w: usage[w["work_id"]])  # みな同じ重みなら、まだ使われていない作品を優先
            pick = elig[:per]
            if len(pick) < per:
                st["notes"].append(f"{pr['name']}: 投稿できる作品が{len(pick)}件しかありません")
            span = max((end - start).total_seconds(), 60)
            # 窓の中で等間隔に区切り、各区間内でランダムに選ぶ(同じ時刻に固まりにくい)
            for i, w in enumerate(pick):
                seg = span / max(len(pick), 1)
                t = start + timedelta(seconds=seg * i + random.uniform(0, seg))
                plan.append((w, pr, t.replace(second=0, microsecond=0)))
                usage[w["work_id"]] += 1
        st["total"] = len(plan)
        sem = asyncio.Semaphore(2)

        async def one(w, pr, t):
            async with sem:
                try:
                    await prep_one(w, pr, t, job)
                except Exception as e:  # noqa: BLE001
                    st["errors"].append(f"{pr['name']}: {str(e)[:120]}")
                st["done"] += 1

        await asyncio.gather(*(one(*x) for x in plan))
        st["state"] = "finished"
    except Exception as e:  # noqa: BLE001
        st["state"] = "error"
        st["errors"].append(str(e)[:200])
