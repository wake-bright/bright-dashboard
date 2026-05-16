#!/bin/bash
# bright-dashboard 自動更新スクリプト
# crontab: 0 7 * * * /Users/yoshi-mac/bright-dashboard/update.sh >> /Users/yoshi-mac/bright-dashboard/update.log 2>&1

cd /Users/yoshi-mac/bright-dashboard

echo "=== $(date '+%Y-%m-%d %H:%M') 更新開始 ==="

# PATH設定（cron環境用）
export PATH="/Users/yoshi-mac/.npm-global/bin:/usr/local/bin:/usr/bin:/bin:$PATH"

# Google認証（bright-seo-reportと共有）
export GOOGLE_APPLICATION_CREDENTIALS="$HOME/.config/gcloud/application_default_credentials.json"

python3 generate.py

if [ $? -eq 0 ]; then
    git add docs/index.html
    git commit -m "auto-update $(date '+%Y-%m-%d')" 2>/dev/null || echo "変更なし"
    git push origin main
    echo "✅ GitHub Pages 更新完了"
else
    echo "❌ generate.py 失敗"
    exit 1
fi

echo "=== 完了 ==="
