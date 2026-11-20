"""インプ達成時の自動リプ(普通用=アフィリエイトリンク / エンタメ用=普通用の最近の投稿URL)。"""
import asyncio
import json
import re
from datetime import datetime, timedelta
from pathlib import Path

from ..api_client import api
from ..config import (ENT, FOLLOWUP_MAX_TRIES, FOLLOWUP_TEXT, FOLLOWUP_TEXT_ENT, FOLLOWUP_WINDOW_H,
                      NORMAL_STATE_DIR, RECOMMEND_N, STATE_DIR)
from ..storage import append_posts_log, read_posts_log
from .works import work_affiliate


FOLLOWUP_FILE = lambda: STATE_DIR / "_followups.json"  # noqa: E731


def fu_load() -> dict:
    f = FOLLOWUP_FILE()
    return json.loads(f.read_text(encoding="utf-8")) if f.exists() else {}


def fu_save(d: dict) -> None:
    FOLLOWUP_FILE().write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")


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


def recent_normal_urls(n: int = RECOMMEND_N) -> list[str]:
    """普通用ボードで最近投稿した投稿のURLを新しい順にn件(なるべく別アカウントから選ぶ)"""
    rows = sorted(posted_tweets(NORMAL_STATE_DIR).items(), key=lambda kv: kv[1]["at"], reverse=True)
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
    job: dict = {}
    for _ in range(30):
        job = ((await asyncio.to_thread(api, "GET", "x/bulk/status", params={"job_id": jid, "id": jid})).get("data")) or {}
        if str(job.get("state")).lower() in ("done", "failed", "error", "finished", "completed"):
            break
        await asyncio.sleep(2)
    if job.get("failed", 0) > 0 or str(job.get("state")).lower() in ("failed", "error"):
        raise RuntimeError(job.get("error") or "Xdeck 側でリプの投稿に失敗しました")
    return str(job.get("tweet_id") or "")


async def run_followups() -> None:
    """インプ達成(Xdeck のインプ通知が reached)した投稿に、同じアカウントから1つ目のリプ(普通用=「続きです〜」/エンタメ用=「おすすめです〜」)を出し、\n    続けてリンクを1件ずつリプでつなげる(普通用=アフィリエイトリンク/エンタメ用=普通用の最近の投稿URL3件)"""
    alerts = (await asyncio.to_thread(api, "GET", "imp-alerts/list"))["data"]["alerts"]
    reached = [a for a in alerts if a.get("status") == "reached"]
    st = fu_load()
    if "_baseline" not in st:
        # 初回は、すでに到達済みの投稿には返信しない(過去分への一斉リプ防止)
        for a in reached:
            st[str(a["tweetId"])] = {"state": "baseline"}
        st["_baseline"] = datetime.now().isoformat(timespec="seconds")
        fu_save(st)
        return
    mine = None
    for a in reached:
        tid = str(a["tweetId"])
        s = st.get(tid)
        if s and s.get("state") in ("baseline", "done", "gave_up"):
            continue
        if mine is None:
            mine = await asyncio.to_thread(posted_tweets)
        m = mine.get(tid)
        if not m:  # このボードで投稿したものではない
            st[tid] = {"state": "baseline"}
            continue
        s = st.setdefault(tid, {"state": "waiting", "tries": 0})
        reached_at = datetime.fromtimestamp((a.get("reachedAt") or 0) / 1000)
        if ENT:  # エンタメ用: 普通用の最近の投稿URLをおすすめとして1件ずつ貼る
            links = await asyncio.to_thread(recent_normal_urls)
            first = FOLLOWUP_TEXT_ENT
            lack = "普通用の投稿が見つかりません"
        else:    # 普通用: 作品のアフィリエイトリンクを貼る
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
                if not rid:
                    s.update(state="gave_up", error="1つ目のリプのIDを取得できず、リンクのリプができませんでした")
                    fu_save(st)
                    continue
                chain.append(rid)
                s["reply1"] = rid
                fu_save(st)
            for link in links[len(chain) - 1:]:
                rid = await post_followup(m["profile_id"], chain[-1], link)
                if not rid:
                    s.update(state="gave_up", error="リプのIDを取得できず、続きのリンクをつなげられませんでした")
                    break
                chain.append(rid)
                fu_save(st)
            else:
                s.update(state="done", at=datetime.now().isoformat(timespec="seconds"), work_id=m["work_id"],
                         url="\n".join(links))
                s.pop("note", None)
                s.pop("error", None)
                print(f"followup: {tid} にリプしました")
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
