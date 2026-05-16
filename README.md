# bright-dashboard

弁護士法人ブライト Webマーケ ダッシュボード

- GA4・GSC・WP記事ステータスを一画面で確認
- ジャンル（企業法務・労災・交通事故・その他）でフィルタリング
- 社内共有用（外部公開禁止）

## 更新方法

```bash
cd ~/bright-dashboard
python3 generate.py   # docs/index.html を再生成
git add docs/index.html && git commit -m "update dashboard" && git push
```
