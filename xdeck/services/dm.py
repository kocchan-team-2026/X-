"""DM まわり: ①一通目の文面に毎回変化をつける ②返信を定期的に確認して通知する。

- 送信は Xdeck の like_dm(投稿にいいねした人へ DM)に任せる。X の DM 送信には Xdeck アプリ内で作る署名が必要で、
  ボードから直接は送れないため。like_dm は「送った相手を記録して二度と送らない」ので二重送信も起きない。
- 返信の確認は、Xdeck が持つアカウントの Cookie で X の受信箱を読むだけ(送信・既読化はしない)。
  対象は DM_GROUPS で指定したグループのアカウントだけ(既定: アダルト2)。
"""
import asyncio
import random
from datetime import datetime

import requests

from ..api_client import api, get_profiles, wait_job, job_error
from ..config import DM_CHECK_MIN, DM_FIRST_DAILY, DM_FIRST_MIN, DM_FIRST_WINDOW_H, DM_GROUPS, STATE_DIR
from ..storage import write_json_atomic

# X のウェブ版が使う公開の bearer(ログイン中の Cookie と一緒に送る)
_BEARER = "AAAAAAAAAAAAAAAAAAAAANRILgAAAAAAnNwIzUejRCOuH5E6I8xnZz4puTs%3D1Zv7ttfk8LF81IUq16cHjhLTvJu4FA33AGWWjCpTnA"
_UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36"

# ---------------- 設定(ボードの「アダルト2」画面から ON/OFF。既定はどちらも OFF) ----------------
def _settings_file():
    return STATE_DIR / "_dm_settings.json"


def get_settings() -> dict:
    """{"first_on": 一通目の自動送信, "reply_on": 返信の確認・通知}。ファイルがなければ両方 OFF"""
    import json
    try:
        d = json.loads(_settings_file().read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        d = {}
    return {"first_on": bool(d.get("first_on", False)), "reply_on": bool(d.get("reply_on", False))}


def set_settings(**kw) -> dict:
    d = get_settings()
    d.update({k: bool(v) for k, v in kw.items() if k in d})
    write_json_atomic(_settings_file(), d)
    return d


def sent_today() -> dict:
    """本日の一通目の送信数(アカウントごとの合計)"""
    today = datetime.now().strftime("%Y-%m-%d")
    sent = (_auto_load().get("sent_today") or {}).values()
    return {"count": sum(v["n"] for v in sent if v.get("date") == today), "limit": DM_FIRST_DAILY}


# ---------------- ①文面に変化をつける ----------------
# 意味は同じまま、書き出し・言い回し・絵文字・結びを組み合わせる(5×4×5=100通り)。直前と同じ文面にはしない。
_OPENINGS = ["いいねありがとう🫶🏻🎀", "いいねありがと〜🫶🏻🎀", "いいねありがとう！🎀", "いいねしてくれてありがと〜🫶🏻", "いいねありがと💕"]
_BODIES = [
    "ひとりでしてる所を見られるのが好きで、いいねしてくれた人には動画送ってるんだけど…",
    "ひとりでしてる姿を見られるのが好きで、いいねくれた人には動画を送ってるんですけど…",
    "ひとりでしてるところを見てもらうのが好きで、いいねしてくれた人に動画送ってるんだけど…",
    "ひとりでしてる所を見られるのが好きだから、いいねしてくれた人には動画を送ってるの…",
]
_ASKS = ["見たい？❤︎", "見たかったりする？❤︎", "よかったら見る？❤︎₍ᐢ·͈༝·͈ᐢ₎", "見てみたい？🫶🏻", "見たいかな？❤︎"]
_last_text: dict[str, str] = {}


def vary_first_dm(name: str | None = None, key: str = "default") -> str:
    """一通目の本文を作る。name(表示名)があれば「◯◯さん」と呼びかける。key ごとに直前と同じ文面を避ける"""
    n = f"{name}さん、" if name else ""
    for _ in range(20):
        text = f"{n}{random.choice(_OPENINGS)}\n\n{random.choice(_BODIES)}{n and name + 'さんも'}{random.choice(_ASKS)}"
        if text != _last_text.get(key):
            break
    _last_text[key] = text
    return text


# 二通目(年齢確認)。相手が「見たい」と返してきたあとに送る。一通目と同じく組み合わせで変化をつける(5×4×5=100通り)
_AGE_OPENINGS = ["わかりました！！", "わかりました〜！", "ありがとう！", "了解です！！", "わかったよ〜！"]
_AGE_THANKS = [
    "動画見たいと思ってくれて嬉しいです🫶🏻🎀",
    "見たいと思ってくれて嬉しい🫶🏻🎀",
    "動画に興味持ってくれて嬉しいです🎀",
    "見たいって言ってくれて嬉しいです💕",
]
_AGE_ASKS = [
    "未成年には動画送れないので年齢教えてもらえますか💭",
    "未成年の人には送れないので、年齢教えてもらってもいいですか💭",
    "未成年には動画送れないから、年齢教えてもらえますか？💭",
    "年齢確認させてください🙏 未成年には送れないので、年齢教えてもらえますか💭",
    "未成年には送れないので、先に年齢だけ教えてもらえますか💭",
]


def vary_age_check_dm(key: str = "default") -> str:
    """二通目(年齢確認)の本文。直前と同じ文面は避ける"""
    for _ in range(20):
        text = f"{random.choice(_AGE_OPENINGS)}\n{random.choice(_AGE_THANKS)}\n\n{random.choice(_AGE_ASKS)}"
        if text != _last_text.get("age:" + key):
            break
    _last_text["age:" + key] = text
    return text


def _names_in(log: list[str], marker: str) -> list[str]:
    """ジョブのログから「marker: @相手」の @相手 を順に取り出す"""
    import re
    return [m.group(1) for l in log if marker in l for m in [re.search(r"@(\w+)\s*$", l.split(marker, 1)[1].strip().rstrip("）)"))] if m]


async def _run_like_dm(profile_id: str, tweet_id: str, text: str, limit: int, already: list[str], dry: bool) -> dict:
    payload = {"kind": "like_dm", "profile_ids": [profile_id], "text": text, "tweet": str(tweet_id), "limit": limit}
    if already:
        payload["already"] = already  # この相手(ユーザーID)には送らない
    if dry:
        payload.update(dryRun=True, dry_run=True)  # どちらの名前で効いても送らないよう、両方付ける
    res = await asyncio.to_thread(api, "POST", "x/bulk", json=payload, timeout=120)
    if res.get("code") != 0:
        raise RuntimeError(res.get("msg") or str(res))
    job = await wait_job(res["data"]["job_id"])
    failed = job.get("failed", 0) > 0 or str(job.get("state")).lower() in ("failed", "error")
    if failed:
        raise RuntimeError(job_error(job))
    return job


async def send_first_dm(profile_id: str, tweet_id: str, name: str | None = None, known_ids: set[str] | None = None,
                        known_names: set[str] | None = None) -> dict:
    """tweet_id にいいねした人のうち、「一度もDMしたことがない」1人に、変化をつけた一通目を送る。
    手順: ①送信なしで確認(dry run)→ ②候補が一度もDMしていない人だけなら、本番で1人に送る。
    known_ids / known_names は、すでに会話がある相手(受信箱+ボードの送信記録)。dry run に出た候補がここに入っていたら送らない。
    返り値: {"ok", "sent"(送った人数), "to"(送った相手), "text", "log", "error"}"""
    known_ids, known_names = known_ids or set(), {n.lower() for n in (known_names or set())}
    text = vary_first_dm(name, key=profile_id)
    out = {"ok": True, "sent": 0, "to": None, "text": text, "log": [], "error": None}
    try:
        dry = await _run_like_dm(profile_id, tweet_id, text, 3, sorted(known_ids), dry=True)
        log = dry.get("log") or []
        if _names_in(log, "DM 送信:"):  # 確認のつもりが送られていた(dry run が効いていない)→ 以後は実行しない
            raise RuntimeError("dry run が効いていません(確認の段階で送信されました)。自動送信を止めてください: " + " / ".join(log)[:200])
        cands = _names_in(log, "送信予定")
        out["log"] = log
        if not cands:  # 送る相手がいない
            return out
        if cands[0].lower() in known_names:
            out.update(ok=False, error=f"@{cands[0]} はすでに会話があるため送りません(除外が効いていません)")
            return out
        real = await _run_like_dm(profile_id, tweet_id, text, 1, sorted(known_ids), dry=False)
        out["log"] = real.get("log") or []
        sent_to = _names_in(out["log"], "DM 送信:")
        out["sent"], out["to"] = len(sent_to), (sent_to[0] if sent_to else None)
        if sent_to and sent_to[0].lower() != cands[0].lower():  # 確認で見た相手と違う人に送られた
            out.update(ok=False, error=f"確認では @{cands[0]} でしたが @{sent_to[0]} に送られました")
    except Exception as e:  # noqa: BLE001
        out.update(ok=False, error=str(e)[:300])
    return out


# ---------------- ②返信の確認 ----------------
def _file():
    return STATE_DIR / "_dm_inbox.json"


def _load() -> dict:
    import json
    f = _file()
    try:
        return json.loads(f.read_text(encoding="utf-8")) if f.exists() else {}
    except Exception:  # noqa: BLE001
        return {}


def _norm(s: str) -> str:
    return s.replace("２", "2").strip()


def dm_profiles() -> list[dict]:
    want = {_norm(g) for g in DM_GROUPS}
    return [p for p in get_profiles() if _norm(p["group"]) in want]


def fetch_inbox(profile_id: str) -> dict | None:
    """アカウントの DM 受信箱(読み取りのみ)。取れなければ None。返り値: {"me", "users", "convs": {conv_id: [message...]}}"""
    ck = api("GET", "cookie/get", params={"profile_id": profile_id})["data"]["cookies"]
    jar = {c["name"]: c["value"] for c in ck}
    if "auth_token" not in jar or "ct0" not in jar:
        return None
    r = requests.get("https://x.com/i/api/1.1/dm/inbox_initial_state.json", cookies=jar, timeout=30,
                     headers={"authorization": "Bearer " + _BEARER, "x-csrf-token": jar["ct0"], "x-twitter-auth-type": "OAuth2Session",
                              "x-twitter-active-user": "yes", "user-agent": _UA},
                     params={"nsfw_filtering_enabled": "false", "dm_secret_conversations_enabled": "false"})
    if r.status_code != 200:
        print(f"dm: 受信箱の取得に失敗 {profile_id[:8]} status={r.status_code}")
        return None
    st = r.json()["inbox_initial_state"]
    convs: dict[str, list[dict]] = {}
    for e in st.get("entries", []):
        m = e.get("message")
        if m:
            convs.setdefault(m["conversation_id"], []).append(m)
    for ms in convs.values():
        ms.sort(key=lambda m: int(m["id"]))
    return {"me": jar.get("twid", "").replace("u%3D", "").replace("u=", ""), "users": st.get("users", {}), "convs": convs}


def new_replies(inbox: dict, seen: dict, first_run: bool) -> tuple[list[dict], dict]:
    """前回より新しい「相手からのメッセージ」を返す。自分が一度でも送った会話だけが対象(スパムの一方的な受信は無視)。
    seen は {会話ID: 見た最後のメッセージID}。first_run は、今ある分を既読にするだけ(過去分を通知しない)"""
    me, users = inbox["me"], inbox["users"]
    out, new_seen = [], dict(seen)
    for cid, ms in inbox["convs"].items():
        last = int(seen.get(cid, 0))
        mine = any(m["message_data"]["sender_id"] == me for m in ms)
        if not first_run and mine:
            for m in ms:
                d = m["message_data"]
                if int(m["id"]) > last and d["sender_id"] != me:
                    u = users.get(d["sender_id"], {})
                    out.append({"message_id": m["id"], "conv": cid, "user_id": d["sender_id"], "screen_name": u.get("screen_name", ""),
                                "name": u.get("name", ""), "text": d.get("text", ""), "time": int(d.get("time") or 0)})
        new_seen[cid] = str(max(int(m["id"]) for m in ms))
    return out, new_seen


async def check_replies() -> int:
    """DM 対象アカウントの受信箱を見て、新しい返信を記録・通知する。返り値: 新しい返信の件数"""
    from .recovery import notify  # 循環 import を避けるため遅く読む
    st, total = _load(), 0
    st.setdefault("seen", {})
    st.setdefault("replies", [])
    for p in await asyncio.to_thread(dm_profiles):
        try:
            inbox = await asyncio.to_thread(fetch_inbox, p["id"])
        except Exception as e:  # noqa: BLE001
            print(f"dm: {p['name']} の受信箱でエラー: {str(e)[:100]}")
            continue
        if inbox is None:
            continue
        first = p["id"] not in st["seen"]
        found, st["seen"][p["id"]] = new_replies(inbox, st["seen"].get(p["id"], {}), first)
        for r in found:
            r.update(profile_id=p["id"], account=p["name"], at=datetime.now().isoformat(timespec="seconds"))
            st["replies"].append(r)
            total += 1
            await notify(f"DM 返信: {p['name']} ← @{r['screen_name'] or r['user_id']}({r['name']})\n{r['text'][:200]}")
        await asyncio.sleep(1)
    st["replies"] = st["replies"][-300:]
    await asyncio.to_thread(write_json_atomic, _file(), st)
    return total


def recent_replies(limit: int = 50) -> list[dict]:
    return list(reversed(_load().get("replies", [])[-limit:]))


async def dm_loop() -> None:
    while True:
        try:
            if not get_settings()["reply_on"]:  # 画面で OFF のあいだは受信箱に触れない
                await asyncio.sleep(30)
                continue
            n = await check_replies()
            if n:
                print(f"dm: 新しい返信 {n} 件")
        except Exception as e:  # noqa: BLE001
            print("dm error:", e)
        await asyncio.sleep(max(1, DM_CHECK_MIN) * 60)


# ---------------- ③一通目の自動送信 ----------------
def _auto_file():
    return STATE_DIR / "_dm_auto.json"


def _auto_load() -> dict:
    import json
    try:
        return json.loads(_auto_file().read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}


def liked_tweet_ids(profile_id: str, hours: int) -> list[str]:
    """アカウントの通知(読み取りのみ)から、直近 hours 時間以内にいいねが付いた自分の投稿(返信も含む)のID。新しい順"""
    import time
    ck = api("GET", "cookie/get", params={"profile_id": profile_id})["data"]["cookies"]
    jar = {c["name"]: c["value"] for c in ck}
    if "auth_token" not in jar or "ct0" not in jar:
        return []
    r = requests.get("https://x.com/i/api/2/notifications/all.json", cookies=jar, timeout=30,
                     headers={"authorization": "Bearer " + _BEARER, "x-csrf-token": jar["ct0"], "x-twitter-auth-type": "OAuth2Session",
                              "x-twitter-active-user": "yes", "user-agent": _UA}, params={"count": 40, "include_entities": "false"})
    if r.status_code != 200:
        print(f"dm: 通知の取得に失敗 status={r.status_code}")
        return []
    notes = r.json().get("globalObjects", {}).get("notifications", {})
    since, out = (time.time() - hours * 3600) * 1000, []
    for n in sorted(notes.values(), key=lambda n: -int(n["timestampMs"])):
        if int(n["timestampMs"]) < since or "いいね" not in n.get("message", {}).get("text", ""):
            continue
        for t in n.get("template", {}).get("aggregateUserActionsV1", {}).get("targetObjects", []):
            tid = (t.get("tweet") or {}).get("id")
            if tid and tid not in out:
                out.append(tid)
    return out


async def auto_first_dm_once() -> str:
    """1回の確認で、条件を満たす最初の投稿のいいね主1人に一通目を送る。送ったら1人で終了。返り値は結果の説明"""
    from .recovery import notify
    st, today = _auto_load(), datetime.now().strftime("%Y-%m-%d")
    st.setdefault("sent_today", {}).update({k: v for k, v in st["sent_today"].items() if v.get("date") == today})
    st.setdefault("exhausted", {})
    now = datetime.now().timestamp()
    st["exhausted"] = {k: v for k, v in st["exhausted"].items() if now - v < 3600}  # 送る相手がいなかった投稿は1時間見ない
    msg = "対象なし"
    for p in await asyncio.to_thread(dm_profiles):
        day = st["sent_today"].get(p["id"], {"date": today, "n": 0})
        if day["n"] >= DM_FIRST_DAILY:
            msg = f"{p['name']}: 本日の上限({DM_FIRST_DAILY}人)に達しました"
            continue
        tweets = [t for t in await asyncio.to_thread(liked_tweet_ids, p["id"], DM_FIRST_WINDOW_H) if t not in st["exhausted"]][:5]
        ids, names = set(), {r.lower() for r in st.get("recipients", [])}
        ib = await asyncio.to_thread(fetch_inbox, p["id"])  # すでに会話がある相手(一度でもDMしたことがある人)を除く
        if ib:
            ids = {u for cid in ib["convs"] for u in cid.split("-")} - {ib["me"]}
            names |= {u.get("screen_name", "").lower() for u in ib["users"].values() if u.get("screen_name")}
        for tid in tweets:
            res = await send_first_dm(p["id"], tid, known_ids=ids, known_names=names)
            if res["error"]:
                msg = f"{p['name']}: 送信しませんでした {res['error'][:100]}"
                st["exhausted"][tid] = now  # 同じ投稿で繰り返さない
                await notify(f"DM 一通目を送りませんでした: {p['name']}\n{res['error'][:200]}")
                if "dry run が効いていません" in res["error"]:  # 安全のため自動送信を止める
                    set_settings(first_on=False)
                break
            if res["sent"] == 0:
                st["exhausted"][tid] = now
                continue
            day = {"date": today, "n": day["n"] + 1}
            st["sent_today"][p["id"]] = day
            who = "@" + res["to"] if res["to"] else ""
            if res["to"]:
                st.setdefault("recipients", []).append(res["to"])  # ボードが送った相手の記録(二度と送らない)
            msg = f"{p['name']}: 一通目を送信 {who}(本日 {day['n']}/{DM_FIRST_DAILY})"
            await notify(f"DM 一通目を送信: {msg}\n{res['text'][:120]}")
            break
        await asyncio.to_thread(write_json_atomic, _auto_file(), st)
    await asyncio.to_thread(write_json_atomic, _auto_file(), st)
    return msg


async def dm_first_loop() -> None:
    await asyncio.sleep(60)  # 起動直後は他の処理を優先
    while True:
        try:
            if not get_settings()["first_on"]:  # 画面で OFF のあいだは送らない
                await asyncio.sleep(30)
                continue
            print("dm first:", await auto_first_dm_once())
        except Exception as e:  # noqa: BLE001
            print("dm first error:", e)
        await asyncio.sleep(max(1, DM_FIRST_MIN) * 60)
