"""旧レイアウト(saved/・saved_ent/)から data/<board>/{posts,state}/ への移行。

起動のたびに呼ばれ、旧フォルダがなければ何もしない。アダルト用・エンタメ用のボードが同時に起動しても
重複しないよう、最初に旧フォルダを atomic に rename できたほうだけが仕分けを行う。
"""
import sys
import time
from pathlib import Path

from .config import DATA_ROOT, ROOT

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
