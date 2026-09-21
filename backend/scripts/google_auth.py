"""Google Calendar と連携する。最初に 1 回だけ実行する（#43）。

    .venv/bin/python -m scripts.google_auth

ブラウザで Google にログインして「許可」を押すと、トークンを GOOGLE_TOKEN_PATH
（既定 backend/.google_token.json）に保存する。以降 Backend はこれを読んで
Calendar API を呼び、アクセストークンの期限切れも自分で取り直す。

事前に必要なもの:

  - backend/.env の GOOGLE_CLIENT_ID / GOOGLE_CLIENT_SECRET
    （OAuth クライアントの種類は「デスクトップアプリ」）
  - 使う Google アカウントが、OAuth 同意画面のテストユーザーに入っていること

テスト公開中のアプリでは、リフレッシュトークンが 7 日で失効する。
Backend が「連携の期限が切れました」を返したら、これをもう一度実行する。

WSL などでブラウザが開かないときは、表示された URL を手元のブラウザで開けばよい。
"""

from __future__ import annotations

import argparse
import os
import sys
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from google_auth_oauthlib.flow import InstalledAppFlow
from oauthlib.oauth2.rfc6749.errors import AccessDeniedError, OAuth2Error

from config import get_settings
from tools.google_calendar import SCOPES

# Google の同意画面では、利用者が権限のチェックを外して許可できる。
# そのとき oauthlib は既定で例外にしてしまうので、受け取ってから自分で確かめる。
os.environ.setdefault("OAUTHLIB_RELAX_TOKEN_SCOPE", "1")

WAIT_SECONDS = 300


def _wait_for_redirect(port: int, state: str) -> str:
    """Google から戻ってきたアクセスの path（?code=...&state=...）を返す。

    ライブラリの run_local_server は最初の 1 回のアクセスしか受け取らない。
    前回の戻り先タブの読み込み直しや、エディタのポート確認が先に来ると、
    それを Google からの戻りとして照合して失敗する（MismatchingStateError）。
    ここでは state が一致するアクセスが来るまで待ち続け、ほかは無視する。
    """
    received: list[str] = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            url = urlparse(self.path)
            if parse_qs(url.query).get("state") != [state]:
                # 照合値や認可コードは出さない。どこへのアクセスだったかだけ示す。
                print(f"（関係のないアクセスを無視しました: {url.path}）", file=sys.stderr)
                self._reply(404, "このページは使われていません。")
                return
            received.append(self.path)
            self._reply(200, "受け取りました。ターミナルに戻って結果を確認してください。")

        def _reply(self, status: int, message: str) -> None:
            body = f"<!doctype html><meta charset='utf-8'><p>{message}</p>".encode()
            self.send_response(status)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *_: object) -> None:
            # 既定のアクセスログは URL（認可コード入り）をそのまま出すので止める。
            pass

    deadline = time.monotonic() + WAIT_SECONDS
    with HTTPServer(("localhost", port), Handler) as server:
        server.timeout = 1
        while not received:
            if time.monotonic() > deadline:
                raise TimeoutError
            server.handle_request()
    return received[0]


def main() -> int:
    parser = argparse.ArgumentParser(description="Google Calendar と連携してトークンを保存する")
    parser.add_argument("--port", type=int, default=8765, help="認証の戻り先にするローカルのポート")
    parser.add_argument(
        "--no-browser", action="store_true", help="ブラウザを自動で開かず、URL だけ表示する"
    )
    args = parser.parse_args()

    settings = get_settings()
    if not settings.google_client_id or not settings.google_client_secret:
        print(
            "backend/.env に GOOGLE_CLIENT_ID と GOOGLE_CLIENT_SECRET を設定してください。",
            file=sys.stderr,
        )
        return 1

    flow = InstalledAppFlow.from_client_config(
        {
            "installed": {
                "client_id": settings.google_client_id,
                "client_secret": settings.google_client_secret,
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
            }
        },
        scopes=SCOPES,
    )
    flow.redirect_uri = f"http://localhost:{args.port}/"
    # prompt=consent: 前に許可したアカウントでも、毎回リフレッシュトークンを受け取る。
    auth_url, state = flow.authorization_url(prompt="consent")

    print(
        "\nブラウザで次の URL を開き、テストユーザーの Google アカウントで許可してください:\n"
        f"{auth_url}\n"
    )
    if not args.no_browser:
        webbrowser.open(auth_url, new=1)

    try:
        path = _wait_for_redirect(args.port, state)
    except TimeoutError:
        print(f"{WAIT_SECONDS // 60} 分待っても許可されませんでした。", file=sys.stderr)
        return 1
    except OSError:
        print(
            f"ポート {args.port} が使われています。--port で別の番号を指定してください。",
            file=sys.stderr,
        )
        return 1

    try:
        # oauthlib は https 以外の戻り先を拒む。戻り先は同じ PC の中（localhost）なので
        # 通信は外に出ない。ライブラリの run_local_server も同じ扱いをしている。
        flow.fetch_token(authorization_response=f"https://localhost:{args.port}{path}")
    except AccessDeniedError:
        print(
            "Google の画面で許可されませんでした。"
            "テストユーザーに入っているアカウントで、「許可」を押してください。",
            file=sys.stderr,
        )
        return 1
    except OAuth2Error as exc:
        # error はエラーの種類を表す短い文字列で、Secret は含まない。
        print(
            f"Google との連携に失敗しました（{exc.error}）。もう一度実行してください。",
            file=sys.stderr,
        )
        return 1
    creds = flow.credentials

    # 要求した権限ではなく、実際に許可された権限を見る。
    granted = set(creds.granted_scopes or [])
    if not set(SCOPES) <= granted:
        print(
            "カレンダーへのアクセスが許可されていません。"
            "同意画面でカレンダーの項目にチェックを入れて、もう一度実行してください。",
            file=sys.stderr,
        )
        return 1
    if not creds.refresh_token:
        print(
            "リフレッシュトークンを受け取れませんでした。"
            "https://myaccount.google.com/permissions でこのアプリのアクセスを削除してから、"
            "もう一度実行してください。",
            file=sys.stderr,
        )
        return 1

    token_path = Path(settings.google_token_path)
    # 本人以外が読めないように作る。中身は画面にも Log にも出さない。
    fd = os.open(token_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(creds.to_json())
    token_path.chmod(0o600)
    print(f"保存しました: {token_path.resolve()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
