"""インプ達成時の自動リプ(アダルト用=アフィリエイトリンク / エンタメ用=アダルト用の最近の投稿URL)。"""
import asyncio
import json
import re
from datetime import datetime, timedelta
from pathlib import Path

from ..api_client import JobTimeout, api, job_error, wait_job
from ..config import (ENT, FOLLOWUP_MAX_TRIES, LIKE_CHECK_MIN, LIKE_TARGET, LIKE_WINDOW_H, FOLLOWUP_TEXT, FOLLOWUP_TEXT_ENT, FOLLOWUP_WINDOW_H,
                      ADULT_STATE_DIR, RECOMMEND_N, STATE_DIR)
from ..storage import append_posts_log, read_posts_log, write_json_atomic
from .works import work_affiliate


FOLLOWUP_FILE = lambda: STATE_DIR / "_followups.json"  # noqa: E731


def fu_load() -> dict:
    f = FOLLOWUP_FILE()
    return json.loads(f.read_text(encoding="utf-8")) if f.exists() else {}


def fu_save(d: dict) -> None:
    write_json_atomic(FOLLOWUP_FILE(), d)


def posted_tweets(d: Path | None = None) -> dict[str, dict]:
    """このボードから投稿した {tweet_id: {work_id, profile_id, at}}(即時投稿の記録 + 予約投稿の完了分)。
    d を渡すと別ボード(保存先フォルダ)の分を返す"""
    d = d or STATE_DIR
    out: dict[str, dict] = {}
    for e in read_posts_log(d):
        r = e.get("response") or {}
        tid = str((r.get("data") or {}).get("tweet_id") or "")
        if e.get("event") == "response" and r.get("code") == 0 and tid:
            out[tid] = {"work_id": e.get("work_id", ""), "profile_id": e.get("profile_id", ""), "at": e.get("at", "")}
    sf = d / "_schedule.json"
    for x in (json.loads(sf.read_text(encoding="utf-8")) if sf.exists() else []):
        m = re.search(r"/status/(\d+)", x.get("link") or "")
        if x["status"] == "done" and m:
            out[m.group(1)] = {"work_id": x["work_id"], "profile_id": x["profile_id"], "at": x.get("finished") or x["at"]}
    return out


def recent_adult_urls(n: int = RECOMMEND_N) -> list[str]:
    """アダルト用ボードで最近投稿した投稿のURLを新しい順にn件(なるべく別アカウントから選ぶ)"""
    rows = sorted(posted_tweets(ADULT_STATE_DIR).items(), key=lambda kv: kv[1]["at"], reverse=True)
    picked: list[tuple[str, str]] = []
    seen: set[str] = set()
    for tid, m in rows:  # まず別アカウントを優先
        if m["profile_id"] not in seen and len(picked) < n:
            seen.add(m["profile_id"])
            picked.append((tid, m["profile_id"]))
    for tid, m in rows:  # 足りなければ同じアカウントの新しい順で補う
        if len(picked) >= n:
            break
        if all(tid != p[0] for p in picked):
            picked.append((tid, m["profile_id"]))
    names: dict[str, str] = {}
    urls = []
    for tid, pid in picked:
        if pid not in names:
            try:
                names[pid] = api("GET", "x/get", params={"profile_id": pid})["data"]["profile"]["screenName"]
            except Exception:  # noqa: BLE001
                names[pid] = "i"  # x.com/i/status/ID でも開ける
        urls.append(f"https://x.com/{names[pid]}/status/{tid}")
    return urls


async def post_followup(profile_id: str, tweet_id: str, text: str) -> str:
    """対象ツイートへのリプとして投稿し、完了まで待つ。投稿したリプのツイートIDを返す(失敗は例外)"""
    payload = {"kind": "post", "profile_ids": [profile_id], "text": text, "reply_to": tweet_id}
    append_posts_log({"at": datetime.now().isoformat(timespec="seconds"), "event": "followup_request",
                      "profile_id": profile_id, "reply_to": tweet_id, "text": text})
    res = await asyncio.to_thread(api, "POST", "x/bulk", json=payload, timeout=300)
    if res.get("code") != 0:
        raise RuntimeError(res.get("msg") or str(res))
    jid = (res.get("data") or {}).get("job_id")
    job = await wait_job(jid)
    if job.get("failed", 0) > 0 or str(job.get("state")).lower() in ("failed", "error"):
        raise RuntimeError(job_error(job, "Xdeck 側でリプの投稿に失敗しました"))
    return str(job.get("tweet_id") or "")


_like_checked = datetime.min


async def liked_enough(st: dict, mine: dict[str, dict]) -> list[dict]:
    """このボードから最近(LIKE_WINDOW_H時間以内)投稿した投稿のうち、いいねが LIKE_TARGET 以上のもの。
    Xdeck のインプ通知と同じ形({tweetId, reachedAt})で返す。確認は LIKE_CHECK_MIN 分おき"""
    global _like_checked
    if LIKE_TARGET <= 0 or datetime.now() - _like_checked < timedelta(minutes=LIKE_CHECK_MIN):
        return []
    _like_checked = datetime.now()
    since = (datetime.now() - timedelta(hours=LIKE_WINDOW_H)).isoformat(timespec="seconds")
    cands = {t: m for t, m in mine.items()
             if m["at"] >= since and (st.get(t) or {}).get("state") not in ("baseline", "done", "gave_up")}
    sem = asyncio.Semaphore(4)
    hit: list[dict] = []

    async def one(tid: str, m: dict) -> None:
        async with sem:
            try:
                r = await asyncio.to_thread(api, "GET", "x/tweet", params={"profile_id": m["profile_id"], "tweet": tid}, timeout=90)
                likes = ((r.get("data") or {}).get("counts") or {}).get("favorites") or 0
            except Exception as e:  # noqa: BLE001
                print(f"followup: いいね数の取得に失敗 {tid}: {str(e)[:80]}")
                return
        if likes >= LIKE_TARGET:
            hit.append({"tweetId": tid, "reachedAt": datetime.now().timestamp() * 1000})

    await asyncio.gather(*(one(t, m) for t, m in cands.items()))
    return hit


async def run_followups() -> None:
    """インプ達成(Xdeck のインプ通知が reached)した投稿に、同じアカウントから1つ目のリプ(アダルト用=「続きです〜」/エンタメ用=「おすすめです〜」)を出し、\n    続けてリンクを1件ずつリプでつなげる(アダルト用=アフィリエイトリンク/エンタメ用=アダルト用の最近の投稿URL3件)"""
    # status=reached で絞って取る(絞らないと、待機中の通知が200件を超えたとき、達成済みが一覧から漏れる)
    alerts = (await asyncio.to_thread(api, "GET", "imp-alerts/list", params={"status": "reached"}))["data"]["alerts"]
    reached = [a for a in alerts if a.get("status") == "reached"]
    st = fu_load()
    if "_baseline" not in st:
        # 初回は、すでに到達済みの投稿には返信しない(過去分への一斉リプ防止)
        for a in reached:
            st[str(a["tweetId"])] = {"state": "baseline"}
        st["_baseline"] = datetime.now().isoformat(timespec="seconds")
        fu_save(st)
        return
    mine = await asyncio.to_thread(posted_tweets)
    have = {str(a["tweetId"]) for a in reached}
    reached += [a for a in await liked_enough(st, mine) if a["tweetId"] not in have]  # いいね数での到達も同じ扱い
    for a in reached:
        tid = str(a["tweetId"])
        s = st.get(tid)
        if s and s.get("state") in ("baseline", "done", "gave_up"):
            continue
        m = mine.get(tid)
        if not m:  # このボードで投稿したものではない
            st[tid] = {"state": "baseline"}
            continue
        s = st.setdefault(tid, {"state": "waiting", "tries": 0})
        reached_at = datetime.fromtimestamp((a.get("reachedAt") or 0) / 1000)
        if ENT:  # エンタメ用: アダルト用の最近の投稿URLをおすすめとして1件ずつ貼る
            links = await asyncio.to_thread(recent_adult_urls)
            first = FOLLOWUP_TEXT_ENT
            lack = "アダルト用の投稿が見つかりません"
        else:    # アダルト用: 作品のアフィリエイトリンクを貼る
            url = await asyncio.to_thread(work_affiliate, m["work_id"])
            links = [url] if url else []
            first = FOLLOWUP_TEXT
            lack = "作品にアフィリエイトリンクが未登録"
        if not links:
            s["state"] = "waiting"
            s["note"] = lack
            if datetime.now() - reached_at > timedelta(hours=FOLLOWUP_WINDOW_H):
                s["state"] = "gave_up"
            continue
        try:
            # 元ツイート →「続きです〜/おすすめです〜」→ リンク1 → リンク2 … と1件ずつ返信をつなげる。
            # 投稿済みの分は chain に残し、再試行時にやり直さない
            chain = s.setdefault("chain", [])
            if s.get("reply1") and not chain:  # 旧形式の記録からの引き継ぎ
                chain.append(s["reply1"])
            if not chain:
                rid = await post_followup(m["profile_id"], tid, first)
                if not rid:  # Xdeck は成功(ok)でもリプのIDを返さないことがある。元ツイートにぶら下げて続ける
                    s["note_no_id"] = "1つ目のリプのIDが取れなかったため、リンクは元の投稿へのリプにしました"
                chain.append(rid or tid)
                s["reply1"] = rid or tid
                fu_save(st)
            for link in links[len(chain) - 1:]:
                rid = await post_followup(m["profile_id"], chain[-1], link)
                chain.append(rid or chain[-1])  # IDが取れないときは同じ親にぶら下げる
                fu_save(st)
            else:
                s.update(state="done", at=datetime.now().isoformat(timespec="seconds"), work_id=m["work_id"],
                         url="\n".join(links))
                s.pop("note", None)
                s.pop("error", None)
                print(f"followup: {tid} にリプしました")
        except JobTimeout as e:  # 投稿できたか不明なので、二重リプを避けて再試行しない
            s.update(state="gave_up", error=str(e)[:200])
            print(f"followup: {tid} {e}")
        except Exception as e:  # noqa: BLE001
            s["tries"] = s.get("tries", 0) + 1
            s["error"] = str(e)[:200]
            if s["tries"] >= FOLLOWUP_MAX_TRIES:
                s["state"] = "gave_up"
            print(f"followup: {tid} 失敗({s['tries']}/{FOLLOWUP_MAX_TRIES}): {e}")
        fu_save(st)
    fu_save(st)


async def followup_loop() -> None:
    while True:
        try:
            await run_followups()
        except Exception as e:  # noqa: BLE001
            print("followup error:", e)
        await asyncio.sleep(180)
