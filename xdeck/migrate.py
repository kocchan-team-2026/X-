"""旧レイアウト(saved/・saved_ent/)から data/<board>/{posts,state}/ への移行。

起動のたびに呼ばれ、旧フォルダがなければ何もしない。アダルト用・エンタメ用のボードが同時に起動しても
重複しないよう、最初に旧フォルダを atomic に rename できたほうだけが仕分けを行う。
"""
import json
import sys
import time
from pathlib import Path

from .config import DATA_ROOT, ENT, ROOT, STATE_DIR

LEGACY = {"adult": ROOT / "saved", "ent": ROOT / "saved_ent"}


def _migrate(legacy: Path, board: Path) -> None:
    if board.exists() or not legacy.is_dir():
        return
    DATA_ROOT.mkdir(parents=True, exist_ok=True)
    work = DATA_ROOT / f".{board.name}.migrating"
    try:
        legacy.rename(work)  # atomic。勝ったほうだけが仕分ける
    except OSError:
        for _ in range(240):  # 別のプロセスが移行中: 終わるまで待つ
            if board.exists():
                return
            time.sleep(0.5)
        sys.exit(f"データの移行が終わりません。{work} を確認してください")
    posts, state = work / "posts", work / "state"
    children = list(work.iterdir())
    posts.mkdir()
    state.mkdir()
    for c in children:  # "_" 始まり・隠しファイル = 管理データ、それ以外 = 保存した投稿
        c.rename((state if c.name.startswith(("_", ".")) else posts) / c.name)
    work.rename(board)
    print(f"migrate: {legacy.name}/ -> {board}/", flush=True)


def migrate_legacy_data() -> None:
    for name, legacy in LEGACY.items():
        _migrate(legacy, DATA_ROOT / name)


def repair_sched_paths() -> None:
    """予約(_schedule.json)に記録された添付ファイルのパスが旧レイアウト(saved/_sched/…)のままなら、
    移行後の場所(state/_sched/…)に直す。直さないと、移行前に入れた予約が「ファイルなし」で失敗する。
    このボード自身の予約だけを、ボード起動時(予約の処理が始まる前)に直す"""
    f = STATE_DIR / "_schedule.json"
    if not f.exists():
        return
    prefix = str(LEGACY["ent" if ENT else "adult"]) + "/"
    items = json.loads(f.read_text(encoding="utf-8"))
    fixed = 0
    for x in items:
        media = []
        for p in x.get("media", []):
            if p.startswith(prefix) and not Path(p).exists():
                new = STATE_DIR / p[len(prefix):]
                if new.exists():
                    p, fixed = str(new), fixed + 1
            media.append(p)
        x["media"] = media
    if fixed:
        tmp = f.with_suffix(".tmp")
        tmp.write_text(json.dumps(items, ensure_ascii=False, indent=1), encoding="utf-8")
        tmp.replace(f)
        print(f"migrate: 予約の添付パスを{fixed}件、新しい場所に直しました", flush=True)
