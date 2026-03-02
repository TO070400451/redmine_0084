#!/usr/bin/env python3
"""
Box OAuth2 初回認証スクリプト。

ブラウザが自動で開くので Box にログインして「Grant access」を押してください。
access_token と refresh_token が .env に自動保存されます。
"""
from __future__ import annotations

import re
import subprocess
import sys
import threading
import urllib.parse
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import requests

ENV_FILE = Path(__file__).parent / ".env"
REDIRECT_URI = "http://localhost:8888/callback"
AUTH_URL = "https://account.box.com/api/oauth2/authorize"
TOKEN_URL = "https://api.box.com/oauth2/token"
TIMEOUT = 300  # 5分


def load_env() -> dict[str, str]:
    env: dict[str, str] = {}
    for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, _, v = line.partition("=")
            env[k.strip()] = v.strip()
    return env


def save_env_values(updates: dict[str, str]) -> None:
    text = ENV_FILE.read_text(encoding="utf-8")
    for key, value in updates.items():
        pattern = rf"^{re.escape(key)}=.*$"
        replacement = f"{key}={value}"
        if re.search(pattern, text, flags=re.MULTILINE):
            text = re.sub(pattern, replacement, text, flags=re.MULTILINE)
        else:
            text = text.rstrip("\n") + f"\n{replacement}\n"
    ENV_FILE.write_text(text, encoding="utf-8")


def exchange_code(client_id: str, client_secret: str, code: str) -> dict:
    resp = requests.post(TOKEN_URL, data={
        "grant_type": "authorization_code",
        "code": code,
        "client_id": client_id,
        "client_secret": client_secret,
        "redirect_uri": REDIRECT_URI,
    })
    resp.raise_for_status()
    return resp.json()


def main() -> None:
    env = load_env()
    client_id = env.get("BOX_CLIENT_ID", "")
    client_secret = env.get("BOX_CLIENT_SECRET", "")

    if not client_id or not client_secret:
        print("ERROR: BOX_CLIENT_ID または BOX_CLIENT_SECRET が .env に設定されていません")
        sys.exit(1)

    params = urllib.parse.urlencode({
        "client_id": client_id,
        "redirect_uri": REDIRECT_URI,
        "response_type": "code",
    })
    auth_url = f"{AUTH_URL}?{params}"

    # コールバックをキャッチするローカルサーバー（0.0.0.0 でバインド）
    code_holder: dict[str, str] = {}
    event = threading.Event()

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            parsed = urllib.parse.urlparse(self.path)
            qs = urllib.parse.parse_qs(parsed.query)
            if "code" in qs:
                code_holder["code"] = qs["code"][0]
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.end_headers()
                self.wfile.write(
                    "<h2 style='font-family:sans-serif'>認証完了！このタブを閉じてください。</h2>".encode()
                )
                event.set()
            else:
                self.send_response(400)
                self.end_headers()

        def log_message(self, *args):
            pass

    server = HTTPServer(("0.0.0.0", 8888), Handler)

    def serve():
        while not event.is_set():
            server.handle_request()

    thread = threading.Thread(target=serve, daemon=True)
    thread.start()

    print("ローカルサーバー起動済み（port 8888）")
    print("ブラウザで Box 認証ページを開きます...\n")

    try:
        subprocess.Popen(["powershell.exe", "-c", f"Start-Process '{auth_url}'"])
    except Exception:
        print(f"ブラウザが開かない場合は以下の URL を手動で開いてください:\n{auth_url}\n")

    print(f"Box にログインして「Grant access」を押してください。（{TIMEOUT}秒待機中）")

    completed = event.wait(timeout=TIMEOUT)

    if not completed:
        print("\nERROR: タイムアウトしました。もう一度やり直してください。")
        sys.exit(1)

    print("\n認証コード取得。トークンを交換中...")
    tokens = exchange_code(client_id, client_secret, code_holder["code"])

    access_token = tokens.get("access_token", "")
    refresh_token = tokens.get("refresh_token", "")

    if not access_token or not refresh_token:
        print(f"ERROR: トークン取得失敗: {tokens}")
        sys.exit(1)

    save_env_values({
        "BOX_ACCESS_TOKEN": access_token,
        "BOX_REFRESH_TOKEN": refresh_token,
    })

    print(".env に BOX_ACCESS_TOKEN と BOX_REFRESH_TOKEN を保存しました")
    print(f"  access_token:  {access_token[:8]}...（60分で失効）")
    print(f"  refresh_token: {refresh_token[:8]}...（使用ごとに自動更新）")


if __name__ == "__main__":
    main()
