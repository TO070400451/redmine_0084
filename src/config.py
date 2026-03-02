from __future__ import annotations

import os
from dataclasses import dataclass, field

from dotenv import load_dotenv

load_dotenv()


@dataclass
class Config:
    # Redmine
    redmine_base_url: str = field(
        default_factory=lambda: os.environ["REDMINE_BASE_URL"].rstrip("/")
    )
    redmine_api_key: str = field(default_factory=lambda: os.environ["REDMINE_API_KEY"])
    redmine_project_id: str = field(
        default_factory=lambda: os.environ["REDMINE_PROJECT_ID"]
    )
    poll_interval_seconds: int = field(
        default_factory=lambda: int(os.getenv("POLL_INTERVAL_SECONDS", "120"))
    )
    issue_fetch_limit: int = field(
        default_factory=lambda: int(os.getenv("ISSUE_FETCH_LIMIT", "50"))
    )

    # Teams
    teams_mode: str = field(
        default_factory=lambda: os.getenv("TEAMS_MODE", "bot")
    )  # bot|graph
    teams_target: str = field(
        default_factory=lambda: os.getenv("TEAMS_TARGET", "chat")
    )  # chat|channel

    # Bot
    bot_app_id: str = field(default_factory=lambda: os.getenv("BOT_APP_ID", ""))
    bot_app_password: str = field(
        default_factory=lambda: os.getenv("BOT_APP_PASSWORD", "")
    )
    bot_endpoint_url: str = field(
        default_factory=lambda: os.getenv("BOT_ENDPOINT_URL", "")
    )
    teams_chat_id: str = field(default_factory=lambda: os.getenv("TEAMS_CHAT_ID", ""))

    # Bot server
    bot_server_host: str = field(
        default_factory=lambda: os.getenv("BOT_SERVER_HOST", "0.0.0.0")
    )
    bot_server_port: int = field(
        default_factory=lambda: int(os.getenv("BOT_SERVER_PORT", "3978"))
    )

    # Graph
    ms_tenant_id: str = field(default_factory=lambda: os.getenv("MS_TENANT_ID", ""))
    ms_client_id: str = field(default_factory=lambda: os.getenv("MS_CLIENT_ID", ""))
    ms_client_secret: str = field(
        default_factory=lambda: os.getenv("MS_CLIENT_SECRET", "")
    )

    # Box
    box_mode: str = field(
        default_factory=lambda: os.getenv("BOX_MODE", "api")
    )  # direct|api
    box_access_token: str = field(
        default_factory=lambda: os.getenv("BOX_ACCESS_TOKEN", "")
    )
    box_shared_link_password: str = field(
        default_factory=lambda: os.getenv("BOX_SHARED_LINK_PASSWORD", "")
    )

    # Local
    work_root: str = field(
        default_factory=lambda: os.getenv("WORK_ROOT", "/tmp/redmine_auto")
    )
    db_path: str = field(default_factory=lambda: os.getenv("DB_PATH", "state.db"))

    # Optional
    google_upload_mode: str = field(
        default_factory=lambda: os.getenv("GOOGLE_UPLOAD_MODE", "none")
    )

    # patterns.yaml path (relative to project root or absolute)
    patterns_yaml: str = field(
        default_factory=lambda: os.getenv("PATTERNS_YAML", "config/patterns.yaml")
    )

    # ダッシュボード HTML 出力先
    dashboard_path: str = field(
        default_factory=lambda: os.getenv("DASHBOARD_PATH", "dashboard.html")
    )

    # Web サーバーポート
    web_port: int = field(
        default_factory=lambda: int(os.getenv("WEB_PORT", "8080"))
    )
