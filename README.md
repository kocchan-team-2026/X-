# X保存ボード(Xdeck補助)

Discord に貼った X(Twitter)の投稿リンクから、本文・画像・動画をローカルに保存し、
ブラウザのボードで **作品ごとに管理 → 加工 → Xdeck 経由で投稿・予約** するツールです。

- **普通用ボード**(http://localhost:8765): 作品の保存、リライト、一括予約、予約投稿、
  インプ・シャドウバンの確認、アフィリエイトリンク管理、インプ達成時の自動リプ
- **エンタメ用ボード**(http://localhost:8766、任意): 別チャンネル・別アカウント群用。
  インプ達成時に、普通用で最近投稿した投稿URLを「おすすめ」として自動リプ

## 動作環境

| 必要なもの | 用途 |
|---|---|
| macOS | クリップボード連携(`pbcopy` など)と、アプリ化のため |
| Python 3.10 以上 | 本体 |
| Xdeck(`/Applications/XDeck.app`) | 投稿・予約・インプ取得・シャドウバン判定。アカウントを登録済みで、起動していること |
| ffmpeg(`brew install ffmpeg`) | 動画の加工・サムネイル |
| Discord Bot | リンクの受け取り |
| [Claude Code](https://claude.com/claude-code) の `claude` コマンド | **任意**。本文リライト機能だけに使います |

## セットアップ(5分)

```bash
git clone https://github.com/kocchan-team-2026/X-.git
cd X-
./scripts/setup.sh
```

`scripts/setup.sh` が次をまとめて行います。

1. `.venv` を作り、依存パッケージを入れる
2. ffmpeg / Claude Code / Xdeck が入っているか確認する
3. `.env` を対話で作る(トークンは入力しても画面に表示されません)
4. `~/Applications/Xdeck補助.app` を作る(開くとボードが立ち上がってブラウザで開きます)

あとは **「Xdeck補助」アプリ**(Spotlight で `Xdeck補助`)か、`./scripts/start.sh` を開くだけです。

### 1. Discord Bot を作る

1. <https://discord.com/developers/applications> → **New Application**
2. **Bot** タブ → **Reset Token** でトークンをコピー → これが `DISCORD_BOT_TOKEN`
3. 同じ **Bot** タブの **Privileged Gateway Intents** で **MESSAGE CONTENT INTENT をオン**
   (オフだとメッセージ内のリンクが読めません)
4. **OAuth2 → URL Generator** で `bot` にチェックし、権限は次を選ぶ
   - View Channels / Send Messages / Read Message History / Add Reactions
   - Create Public Threads / Send Messages in Threads
5. 生成された URL を開き、自分のサーバーに Bot を招待する
6. Discord の設定 → 詳細設定 → **開発者モード** をオンにし、使うチャンネルを右クリック →
   **チャンネルIDをコピー**(`.env` の `CHANNEL_IDS` / `CHANNEL_IDS_ENT` に入れる)

### 2. Xdeck の API トークン

Xdeck を起動したまま、API トークンを `.env` の `XDECK_TOKEN` に入れます
(Xdeck の API は既定で `http://127.0.0.1:39150/api/v1`。変えている場合は `XDECK_URL` も設定)。

Xdeck の **グループ名** で、ボードごとの投稿対象が決まります。

| グループ名 | 使われ方 |
|---|---|
| 「エンタメ」を含む(例: `投稿エンタメ`) | エンタメ用ボードの投稿対象 |
| 「ブースト」を含む(例: `ブースト`) | **どちらのボードでも投稿対象外** |
| それ以外(例: `投稿`) | 普通用ボードの投稿対象 |

### 3. `.env` の内容

`.env.example` に全項目と説明があります(`.env` はコミットされません)。主なもの:

| キー | 必須 | 説明 |
|---|---|---|
| `DISCORD_BOT_TOKEN` | ✅ | Bot のトークン |
| `XDECK_TOKEN` | ✅ | Xdeck の API トークン |
| `CHANNEL_IDS` | | 普通用が拾うチャンネル。空=エンタメ用以外の全チャンネル |
| `CHANNEL_IDS_ENT` | | エンタメ用が拾うチャンネル。**空ならエンタメ用ボードは起動しません** |
| `IMP_TARGET` | | このインプ数に達したら Discord 通知+自動リプ(初期値 2500) |
| `FOLLOWUP` | | `0` で自動リプを止める |

## 使い方

1. Discord の対象チャンネルに、X の投稿リンクを貼る
   → Bot が保存し、✅ を付けてスレッド(=作品)を作ります
2. 作品のスレッドに MyFans / FANZA の URL を貼ると、作品に紐づきます
3. ボードで作品を開き、アフィリエイトリンク(MyFans で作ったURL)を保存
4. 投稿する:
   - **投稿**: 1アカウントずつ、本文を確認して投稿・予約
   - **一括予約**: アカウントと時間帯(初期値は「今〜2時間後」)を決めると、
     作品をランダムに選んで時間をばらして予約。作品ごとの **選ばれやすさ**(重み)も設定できます
5. **インプ達成時の自動リプ**(普通用): 投稿が `IMP_TARGET` に達すると、Xdeck が Discord に通知し、
   同じアカウントから「続きです〜」→ アフィリエイトリンク の順に返信します
   (作品にリンク未登録なら返信せず、登録した時点で返信します)
6. 予約が失敗したときは、予約一覧の **再試行** ボタンでやり直せます

> ⚠ 自動リプは **実際に X へ投稿します**。最初は `FOLLOWUP=0` にして挙動を確認することをおすすめします。
> 起動した時点で既に目標に達している投稿には返信しません(過去分への一斉リプ防止)。

## 保存されるデータ

すべて手元のフォルダに保存され、`.gitignore` で Git には入りません。

- `data/normal/` … 普通用 / `data/ent/` … エンタメ用(それぞれ中は同じ構成)
  - `posts/` … 保存した投稿(動画・画像・本文。1投稿=1フォルダ)
  - `state/` … 予約・投稿履歴・自動リプの状態・アイコンなどの管理データ
- 旧バージョンの `saved/` `saved_ent/` が残っている場合は、起動時に自動で `data/` へ移します
- `.env` … トークン類
- ログ: `~/Library/Logs/xboard.log`

## よくあるトラブル

| 症状 | 対処 |
|---|---|
| アプリを開いてもボードが開かない | `~/Library/Logs/xboard.log` を見る。`.env` のトークン、Xdeck の起動を確認 |
| Discord にリンクを貼っても反応しない | MESSAGE CONTENT INTENT がオンか、`CHANNEL_IDS` が合っているか、Bot がそのチャンネルを見られるか |
| 予約で `No such file or directory: 'ffprobe'` | `brew install ffmpeg`。アプリ(`scripts/start.sh`)は `/usr/local/bin` と `/opt/homebrew/bin` を自動で探します |
| フォルダを移動したらアプリが動かない | `./scripts/make_app.sh` をもう一度実行 |
| 更新を取り込みたい | `git pull` → アプリを開き直す(依存が増えたときは `./scripts/setup.sh` をもう一度) |

## ファイル構成

```
xdeck/               コード本体(起動: python -m xdeck [ent])
  config.py            設定・定数・データの保存先
  api_client.py        Xdeck API クライアント
  storage.py           予約・投稿履歴の読み書き
  media.py rewrite.py  動画加工 / 本文リライト
  discord_bot.py       Discord Bot(リンクの保存)
  migrate.py           旧 saved/ から data/ への移行
  services/            機能: works avatars scheduler bulk shadowban imps followups
  web/                 ボードのサーバー(routes_*.py)と画面(static/ の html・css・js)
scripts/             setup.sh(初回) / start.sh(起動) / make_app.sh(アプリ作成)
assets/              アプリのアイコン
data/                保存データ(Git に入りません)
.env.example         設定の雛形
```
