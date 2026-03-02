from __future__ import annotations

"""WSL から Windows トースト通知を送る。"""

import logging
import subprocess

logger = logging.getLogger(__name__)

_PS_TEMPLATE = r"""
Add-Type -AssemblyName System.Windows.Forms
$title = {title}
$body = {body}
$balloon = New-Object System.Windows.Forms.NotifyIcon
$balloon.Icon = [System.Drawing.SystemIcons]::Information
$balloon.Visible = $true
$balloon.ShowBalloonTip(5000, $title, $body, [System.Windows.Forms.ToolTipIcon]::Info)
Start-Sleep -Milliseconds 5500
$balloon.Dispose()
"""


def notify(title: str, body: str) -> None:
    """Windows トースト通知を表示する。WSL 環境でのみ動作。"""
    def _esc(s: str) -> str:
        return "'" + s.replace("'", "''")[:200] + "'"

    script = _PS_TEMPLATE.format(title=_esc(title), body=_esc(body))
    try:
        subprocess.Popen(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        logger.info("Toast notification sent: %s", title)
    except FileNotFoundError:
        logger.warning("powershell.exe not found. Skipping toast notification.")
    except Exception as exc:
        logger.warning("Toast notification failed: %s", exc)
