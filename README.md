# redmine-teams-box

Redmine の issue journal を監視し、パターン判定の結果を Teams に通知。
「作業する」が選ばれた場合、Box 共有リンクから ZIP をダウンロード・解凍します。

## アーキテクチャ

```
Redmine (journals) → PatternMatcher → Teams (Adaptive Card)
                                            ↓ 作業する
                                    Box shared_items → ZIP → 解凍 → meta.json
                                       SQLite (journal_id で冪等性管理)
```

## セットアップ

```bash
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt

cp .env.example .env
# .env を環境に合わせて編集
```

## .env 設定

| キー | 説明 |
|------|------|
| `REDMINE_BASE_URL` | Redmine のベース URL（末尾スラッシュなし） |
| `REDMINE_API_KEY` | Redmine の API キー（個人設定 → API アクセスキー） |
| `REDMINE_PROJECT_ID` | 監視するプロジェクト ID（数値または識別子） |
| `POLL_INTERVAL_SECONDS` | ポーリング間隔（秒、デフォルト 120） |
| `TEAMS_MODE` | `bot`（推奨）または `graph` |
| `BOT_APP_ID` | Azure Bot の App ID |
| `BOT_APP_PASSWORD` | Azure Bot の App Password |
| `TEAMS_CHAT_ID` | 送信先チャット/チャンネル ID |
| `BOX_ACCESS_TOKEN` | Box の OAuth2 アクセストークン |
| `WORK_ROOT` | ダウンロード・解凍先のルートディレクトリ |

### Redmine API キーの取得

1. Redmine にログイン
2. 右上のユーザー名 → 「個人設定」
3. 「API アクセスキー」を表示・コピー

### Teams Bot の準備（`TEAMS_MODE=bot`）

1. Azure Portal → Azure Bot を作成
2. App ID / Password を取得
3. Bot のエンドポイント URL を `https://<public-hostname>:3978/api/messages` に設定
   ※ ローカル開発時は [ngrok](https://ngrok.com/) 等でトンネリングが必要
4. Teams チャンネルを Bot に接続し、チャット ID を取得

**社内制約で Bot が利用できない場合**は `TEAMS_MODE=graph` を設定し、
Microsoft Graph API（アプリ登録 + Teams メッセージ送信権限）で代替できます。

### Box 認証

Box は OAuth2 アクセストークン方式を採用しています。

- 個人アカウント：Box 開発者コンソールでアプリを作成し、アクセストークンを発行
- 企業環境：JWT 認証（サービスアカウント）が推奨されますが、
  本ツールはトークン文字列を `.env` に設定する方式を前提とします

**なぜ `shared_items` + `zip_downloads` を使うか？**
Box の共有リンクは「フォルダ」を指している場合が多く、
フォルダはブラウザ直アクセスでのダウンロードが API 上サポートされていません。
`shared_items` で実体（file/folder）を特定し、
folder の場合は `zip_downloads` API で ZIP を作成してからダウンロードします。

## 実行

```bash
# 1回だけ実行
python -m src.main --once

# 常駐デーモン（Ctrl+C で停止）
python -m src.main

# ログレベルを変更して実行
python -m src.main --log-level DEBUG --once
```

## フォルダ構成（出力）

```
WORK_ROOT/
  tickets/
    <issue_id>/
      <yyyymmdd_HHMMSS>_journal_<journal_id>/
        01_raw/
          download.zip   # ダウンロードした ZIP（またはファイル）
        02_extract/
          ...            # 解凍済みファイル
        meta.json        # 処理結果のメタ情報
```

## パターン設定

`config/patterns.yaml` でスコアリングルールを管理します。

```yaml
patterns:
  - pattern_id: "log_analysis"
    name: "ログ解析依頼"
    keywords:
      must: ["ログ", "解析"]     # +20 each
      should: ["再現", "手順"]   # +8 each
      must_not: ["対応不要"]     # -30 each
    regex_rules:
      - regex: "(exception|crash)"
        weight: 15
    link_rules:
      box_link_bonus: 10
    threshold:
      notify_min_score: 55
```

## テスト

```bash
pip install pytest
pytest tests/ -v
```

## 典型エラーと対処

| エラー | 原因 | 対処 |
|--------|------|------|
| `KeyError: REDMINE_BASE_URL` | `.env` が未設定 | `.env.example` を参考に設定 |
| `401 Unauthorized` (Redmine) | API キー不正 | Redmine の個人設定でキーを確認 |
| `404` (Box shared_items) | リンク無効または権限なし | Box リンクと ACCESS_TOKEN を確認 |
| `403` (Box zip_downloads) | フォルダの ZIP 作成権限なし | Box 管理者に API 権限を確認 |
| Teams 通知失敗 | Bot エンドポイントへの到達不可 | ngrok などでパブリック URL を確保 |
| `BadZipFile` | ダウンロードしたファイルが ZIP でない | Box リンクの内容を確認 |
