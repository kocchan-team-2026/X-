"""Claude Code (claude -p) による本文リライト。"""
import json
import re
import subprocess

from .config import STATE_DIR


class RewriteRefused(RuntimeError):
    """リライトを断られた/文章として使えない返答だった(内容の問題。やり直しても同じになりやすい)"""


def rewrite_text(text: str, urls: list[str] | None = None) -> list[str]:
    """Claude Code (claude -p) で本文を強めにリライトし、書き方の違う3案を返す。リンクは本文に含めない。"""
    import random
    body = re.sub(r"https?://\S+", "", text).strip()
    if not body:
        return [text]
    angles = random.sample([
        "語順を入れ替え、文の組み立てを大きく変える",
        "言い切りの短い文にまとめ直す",
        "問いかけや呼びかけの形に変える",
        "口語・話し言葉をより強くして言い換える",
        "体言止めや倒置を使って言い換える",
        "文末表現と接続の仕方をすべて変える",
    ], 3)
    prompt = (
        "次のX(Twitter)投稿の本文を、意味と元の口調・テンションは保ったまま、強めにリライトしてください。\n"
        "元の文とは、語句・語順・文末をはっきり変え、別の文章に見えるレベルで書き直します。\n"
        "ただし次を守ること:\n"
        "- 事実や固有名詞(人名・作品名)は変えない・足さない\n"
        "- ハッシュタグと@メンションはそのまま残す\n"
        "- 元より長くしない。絵文字は元の雰囲気の範囲で\n"
        "- URLは本文に含まれていないので、書かない\n\n"
        "3案を作ります。案ごとに次の方針で書き分けてください:\n"
        + "\n".join(f"案{i + 1}: {a}" for i, a in enumerate(angles))
        + "\n\n出力は、3つの文字列からなるJSON配列のみ。説明や前置きは一切書かない。\n"
        f"【元の文】\n{body}\n"
    )
    res = subprocess.run(["claude", "-p", prompt, "--tools", ""], capture_output=True, text=True,
                         stdin=subprocess.DEVNULL, timeout=180, cwd=str(STATE_DIR))
    out = res.stdout.strip()
    if res.returncode != 0 or not out:
        raise RuntimeError(res.stderr.strip() or "リライトに失敗しました")
    try:
        cands = json.loads(out[out.index("["): out.rindex("]") + 1])
        cands = [c.strip() for c in cands if isinstance(c, str) and c.strip()]
    except Exception:  # noqa: BLE001
        # JSON で返らないのは、断りや説明文が返ったとき。それを投稿文にしてはいけない
        raise RewriteRefused("リライトできませんでした: " + out[:60].replace("\n", " "))
    # 元より極端に長い案は、説明文が混ざったものとして捨てる
    cands = [c for c in cands if len(c) <= len(body) * 2 + 30]
    if not cands:
        raise RewriteRefused("リライト結果が使えませんでした(空、または長すぎます)")
    # 本文にリンクは入れない(元の文にURLがあっても外す)
    return [re.sub(r"\s*https?://\S+", "", c).strip() for c in cands]
