from __future__ import annotations

"""
partner.android.com/approvals/report-uploader への自動アップロード。

Playwright の persistent context でブラウザプロファイルを永続化する。
初回のみ有頭ブラウザが開くので、手動ログイン後に Enter を押す。
以降はセッションが再利用されるためログイン不要。
"""

import logging
import time
from pathlib import Path

from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout

logger = logging.getLogger(__name__)

_UPLOAD_URL = "https://partner.android.com/approvals/report-uploader"
_UPLOAD_TIMEOUT_MS = 180_000   # ファイルサイズが大きい場合を考慮して3分
_POLL_INTERVAL_MS = 3_000      # 完了確認の間隔


def upload_zips(
    zip_files: list[Path],
    profile_dir: str,
) -> dict[str, str]:
    """
    ZIP ファイルのリストを partner portal にアップロードする。

    Args:
        zip_files:   アップロードする ZIP ファイルのリスト（順番通りに処理）
        profile_dir: Playwright が使うブラウザプロファイルディレクトリ

    Returns:
        {zip_path_str: "ok" | "rejected:<message>" | "error:<message>"}
    """
    results: dict[str, str] = {}

    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(
            user_data_dir=profile_dir,
            headless=False,         # 有頭: 状況確認・初回ログイン対応
            args=["--no-sandbox"],
        )
        page = context.new_page()

        # 初回ログイン確認
        logger.info("Navigating to %s", _UPLOAD_URL)
        page.goto(_UPLOAD_URL, timeout=60_000, wait_until="domcontentloaded")
        _wait_for_idle(page, timeout_ms=30_000)

        if "accounts.google.com" in page.url or "partner.android.com" not in page.url:
            logger.info("Not logged in. Waiting for manual login...")
            input(
                "\n[Google Upload] ブラウザでログインしてから Enter を押してください... "
            )
            page.goto(_UPLOAD_URL, timeout=60_000, wait_until="domcontentloaded")
            _wait_for_idle(page, timeout_ms=30_000)

        for zip_path in zip_files:
            logger.info("Uploading: %s", zip_path.name)
            result = _upload_one(page, zip_path)
            results[str(zip_path)] = result
            logger.info("Result [%s]: %s", zip_path.name, result)

        context.close()

    return results


# ---------------------------------------------------------------------------
# Internal
# ---------------------------------------------------------------------------

def _upload_one(page, zip_path: Path) -> str:
    """1 ファイルをアップロードし、結果文字列を返す。"""
    try:
        # ページをリロードして初期状態に戻す
        page.goto(_UPLOAD_URL, timeout=60_000, wait_until="domcontentloaded")
        _wait_for_idle(page, timeout_ms=20_000)

        # ---- ファイルセット ----
        # input[type="file"] が非表示でも set_input_files は動作する
        file_input = page.locator('input[type="file"]').first
        file_input.set_input_files(str(zip_path))
        logger.debug("File input set: %s", zip_path.name)

        # ---- アップロードボタン ----
        upload_btn = (
            page.get_by_role("button", name="Upload").or_(
                page.get_by_role("button", name="アップロード")
            ).or_(
                page.locator('[type="submit"]')
            ).first
        )
        upload_btn.click()
        logger.debug("Upload button clicked")

        # ---- 完了待機 ----
        # アップロード完了 or リジェクトが出るまでポーリング
        deadline = time.time() + (_UPLOAD_TIMEOUT_MS / 1000)
        while time.time() < deadline:
            page.wait_for_timeout(_POLL_INTERVAL_MS)

            rejection = _detect_rejection(page)
            if rejection:
                return f"rejected:{rejection}"

            # ネットワークが落ち着いていればアップロード完了とみなす
            # （大容量ファイルは networkidle まで時間がかかるため、
            #   ここでは「リジェクトなし」を成功の判断基準とする）
            try:
                page.wait_for_load_state("networkidle", timeout=5_000)
                # networkidle になりリジェクトもなければ完了
                rejection = _detect_rejection(page)
                if rejection:
                    return f"rejected:{rejection}"
                return "ok"
            except PlaywrightTimeout:
                # まだ通信中 → 次のポーリングへ
                pass

        # タイムアウト到達 → 最終チェック
        rejection = _detect_rejection(page)
        if rejection:
            return f"rejected:{rejection}"
        return "ok"

    except PlaywrightTimeout:
        return "error:timeout"
    except Exception as exc:
        logger.error("Upload error for %s: %s", zip_path.name, exc, exc_info=True)
        return f"error:{exc}"


def _detect_rejection(page) -> str:
    """
    赤文字のエラーメッセージを検出して返す。見つからなければ空文字。

    検出戦略:
      1. role="alert" または error/reject 系クラスの要素テキスト
      2. CSS color が赤系（r>150, g<80, b<80）の表示要素テキスト
    """
    # 戦略1: セマンティックな error 要素
    for selector in [
        '[role="alert"]',
        '.error',
        '[class*="error"]',
        '[class*="reject"]',
        '[class*="invalid"]',
    ]:
        try:
            loc = page.locator(selector)
            if loc.count() > 0:
                text = loc.first.inner_text(timeout=2_000).strip()
                if text:
                    return text
        except Exception:
            pass

    # 戦略2: JS で赤色テキストを走査
    try:
        red_texts: list[str] = page.evaluate("""
            () => {
                const results = [];
                const elements = document.querySelectorAll('*');
                for (const el of elements) {
                    if (el.children.length > 0) continue;  // リーフ要素のみ
                    const style = window.getComputedStyle(el);
                    if (style.display === 'none' || style.visibility === 'hidden') continue;
                    const m = style.color.match(/rgb\\((\\d+),\\s*(\\d+),\\s*(\\d+)\\)/);
                    if (!m) continue;
                    const [, r, g, b] = m.map(Number);
                    if (r > 150 && g < 80 && b < 80) {
                        const text = (el.innerText || el.textContent || '').trim();
                        if (text && text.length > 0 && text.length < 300) {
                            results.push(text);
                        }
                    }
                }
                return [...new Set(results)];
            }
        """)
        if red_texts:
            return " / ".join(red_texts[:3])
    except Exception:
        pass

    return ""


def _wait_for_idle(page, timeout_ms: int = 10_000) -> None:
    """networkidle を待つ。タイムアウトしても続行する。"""
    try:
        page.wait_for_load_state("networkidle", timeout=timeout_ms)
    except PlaywrightTimeout:
        pass
