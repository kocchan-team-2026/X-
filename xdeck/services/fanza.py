"""FANZA のURLから、DMMアフィリエイトのリンクを自動で作る。

DMM アフィリエイトAPI v3(ItemList)に品番(cid)を渡すと、自分のアフィリエイトID入りのリンク
(https://al.fanza.co.jp/?lurl=<商品ページ>&af_id=<ID>&ch=api)が返る。API で商品が見つからないときは作らない(存在しない商品のリンクを入れないため)。
.env に DMM_API_ID と DMM_AFFILIATE_ID(例: xxxx-990)が必要。
"""
import re
from urllib.parse import parse_qs, unquote, urlparse

import requests

from ..config import DMM_AFFILIATE_ID, DMM_API_ID

API = "https://api.dmm.com/affiliate/v3/ItemList"
CID_PATH_RE = re.compile(r"/cid=([a-z0-9_]+)", re.I)


def enabled() -> bool:
    return bool(DMM_API_ID and DMM_AFFILIATE_ID)


def extract_cid(url: str) -> str:
    """FANZA のURLから品番(cid)を取り出す。分からなければ空文字。
    対応: video.dmm.co.jp/.../content/?id=<cid> / dmm.co.jp/.../-/detail/=/cid=<cid>/ / 他人のアフィリエイトリンク(lurl=の中身)"""
    p = urlparse(url)
    q = parse_qs(p.query)
    if q.get("lurl"):  # すでにアフィリエイトリンクの形なら、中のURLを見る
        return extract_cid(unquote(q["lurl"][0]))
    if q.get("id"):
        return q["id"][0].strip().lower()
    if q.get("cid"):
        return q["cid"][0].strip().lower()
    m = CID_PATH_RE.search(p.path)
    return m.group(1).lower() if m else ""


def make_link(url: str) -> str:
    """FANZA のURLからアフィリエイトリンクを作る。作れなければ空文字(例外は出さない)"""
    if not enabled():
        return ""
    cid = extract_cid(url)
    if not cid:
        return ""
    try:
        r = requests.get(API, params={"api_id": DMM_API_ID, "affiliate_id": DMM_AFFILIATE_ID, "site": "FANZA",
                                      "cid": cid, "output": "json"}, timeout=20)
        r.raise_for_status()
        items = [i for i in (r.json().get("result") or {}).get("items", []) if i.get("content_id", "").lower() == cid]
        items.sort(key=lambda i: i.get("service_code") != "digital")  # 単品販売(digital)のページを優先
        if items and items[0].get("affiliateURL"):
            return items[0]["affiliateURL"]
    except Exception as e:  # noqa: BLE001
        print("fanza api error:", str(e)[:100])
    return ""  # APIで商品が見つからない/通信エラーのときは作らない(存在しない商品のリンクを入れない)
