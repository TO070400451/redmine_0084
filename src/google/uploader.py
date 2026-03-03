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


_BATCH_SIZE = 10  # 同時アップロード上限（これを超えるとハングの報告あり）


def upload_zips(
    zip_files: list[Path],
    profile_dir: str,
) -> dict[str, str]:
    """
    ZIP ファイルのリストを partner portal にアップロードする。

    バッチ制御:
      - 01_CTS Results 配下かつ Modules フォルダ外の ZIP（メインログ）は 1 件ずつ
      - その他は最大 _BATCH_SIZE 件ずつまとめてアップロード

    Args:
        zip_files:   アップロードする ZIP ファイルのリスト
        profile_dir: Playwright が使うブラウザプロファイルディレクトリ

    Returns:
        {zip_path_str: "ok" | "rejected:<message>" | "error:<message>"}
    """
    # メインログ（大容量）とその他に分類
    main_files = [z for z in zip_files if _is_main_log(z)]
    other_files = [z for z in zip_files if not _is_main_log(z)]

    # バッチリスト作成: メインは1件ずつ、その他は最大 _BATCH_SIZE 件
    batches: list[list[Path]] = [[z] for z in main_files]
    for i in range(0, len(other_files), _BATCH_SIZE):
        batches.append(other_files[i : i + _BATCH_SIZE])

    if not batches:
        return {}

    logger.info(
        "Upload plan: %d main-log batch(es), %d other batch(es) (batch_size=%d)",
        len(main_files),
        len(range(0, len(other_files), _BATCH_SIZE)),
        _BATCH_SIZE,
    )

    results: dict[str, str] = {}

    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(
            user_data_dir=profile_dir,
            headless=False,         # 有頭: 状況確認・初回ログイン対応
            args=["--no-sandbox"],
            ignore_https_errors=True,  # 社内プロキシによる証明書エラーを無視
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

        for batch_idx, batch in enumerate(batches):
            logger.info(
                "Batch %d/%d (%d file(s))", batch_idx + 1, len(batches), len(batch)
            )
            for zip_path in batch:
                logger.info("Uploading: %s", zip_path.name)
                result = _upload_one(page, zip_path)
                results[str(zip_path)] = result
                logger.info("Result [%s]: %s", zip_path.name, result)

        context.close()

    return results


def _is_main_log(zip_path: Path) -> bool:
    """01_CTS Results 配下かつ Modules サブフォルダ外にある ZIP = メインログ（大容量）。"""
    parts = zip_path.parts
    try:
        cts_idx = next(i for i, p in enumerate(parts) if p == "01_CTS Results")
    except StopIteration:
        return False
    # 01_CTS Results/ 以降のパスに "Modules" が含まれていなければメインログ
    return "Modules" not in parts[cts_idx + 1 :]


# ---------------------------------------------------------------------------
# Internal
# ---------------------------------------------------------------------------

def _upload_one(page, zip_path: Path) -> str:
    """1 ファイルをアップロードし、結果文字列を返す。"""
    try:
        # ページをリロードして初期状態に戻す
        logger.info("Navigating to upload page...")
        page.goto(_UPLOAD_URL, timeout=120_000, wait_until="domcontentloaded")
        _wait_for_idle(page, timeout_ms=30_000)
        logger.info("Page loaded: %s", page.url)

        # ---- ファイルセット ----
        # xap-uploader-dropzone をクリックしてファイル選択ダイアログを開く
        logger.info("Looking for upload zone...")
        upload_zone = page.locator("div.xap-uploader-dropzone").first
        upload_zone.scroll_into_view_if_needed(timeout=10_000)
        logger.info("Clicking upload zone to open file chooser...")
        with page.expect_file_chooser(timeout=15_000) as fc_info:
            upload_zone.click(timeout=15_000)
        file_chooser = fc_info.value
        file_chooser.set_files(str(zip_path))
        logger.info("File set via chooser: %s", zip_path.name)

        # ---- アップロードボタン ----
        # ファイル選択後に表示される Submit/Upload ボタンを探す
        logger.info("Looking for upload button...")
        upload_btn = (
            page.get_by_role("button", name="Upload").or_(
                page.get_by_role("button", name="Submit").or_(
                    page.get_by_role("button", name="アップロード")
                )
            ).first
        )
        upload_btn.click(timeout=30_000)
        logger.info("Upload button clicked")

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
