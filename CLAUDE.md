# bright-dashboard（Webマーケダッシュボード）
> バージョン: v0.1 | 親フォルダ: ~/bright-dev/ | GitHub: wake-bright/bright-dashboard

## 概要
弁護士法人ブライト Webマーケ専用ダッシュボード。
GA4・GSC・WP記事ステータスをジャンル別（企業法務・労災・交通事故）で一覧表示。
社内共有用・外部公開禁止。

## 技術スタック
- Python（generate.py でHTML生成）
- 静的HTML出力 → docs/index.html

## 生成方法
```bash
cd ~/bright-dashboard
python generate.py
```

## 出力先
`docs/index.html`（GitHub Pages または直接ブラウザで開く）

## 直近の状態（2026-05-17）
- git管理済み・GitHub同期済み
- BrightOneポータルの「Webマーケティング」セクションから代替参照可能
