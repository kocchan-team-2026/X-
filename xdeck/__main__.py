"""起動: python -m xdeck [ent]"""
import sys

from .config import ENT, ENT_CHANNELS, TOKEN
from .migrate import migrate_legacy_data

if not TOKEN:
    sys.exit(".env に DISCORD_BOT_TOKEN がありません。./scripts/setup.sh を実行するか、.env.example を .env にコピーして入力してください")
if ENT and not ENT_CHANNELS:
    sys.exit("エンタメ用ボードには .env に CHANNEL_IDS_ENT=<チャンネルID> が必要です")

migrate_legacy_data()

from .discord_bot import client  # noqa: E402  (データ移行のあとで読み込む)

client.run(TOKEN)
