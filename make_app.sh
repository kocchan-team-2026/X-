#!/bin/bash
# macOS アプリ「Xdeck補助.app」を作る。開くと start.sh が走り、ボードがブラウザで開く。
# 使い方: ./make_app.sh [作成先フォルダ(初期値: ~/Applications)]
set -e
REPO="$(cd "$(dirname "$0")" && pwd)"
DEST="${1:-$HOME/Applications}"
APP="$DEST/Xdeck補助.app"
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"
cp "$REPO/assets/AppIcon.icns" "$APP/Contents/Resources/AppIcon.icns"
cat > "$APP/Contents/Info.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
<key>CFBundleExecutable</key><string>launcher</string>
<key>CFBundleIdentifier</key><string>local.xdeckhojo.launcher</string>
<key>CFBundleName</key><string>Xdeck補助</string>
<key>CFBundlePackageType</key><string>APPL</string>
<key>CFBundleIconFile</key><string>AppIcon</string>
<key>LSUIElement</key><true/>
</dict></plist>
PLIST
cat > "$APP/Contents/MacOS/launcher" <<LAUNCH
#!/bin/bash
exec "$REPO/start.sh"
LAUNCH
chmod +x "$APP/Contents/MacOS/launcher"
touch "$APP"
echo "作成しました: $APP"
echo "(このフォルダを移動したら、./make_app.sh をもう一度実行してください)"
