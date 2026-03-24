#!/usr/bin/env python3
"""
Telegram Bot — スマホからX投稿生成を指示
==========================================
Telegram からメッセージを送ると、generate_posts.sh を実行して
投稿候補を生成し、結果を返信する。

Max Plan 定額内で動作（claude CLI 経由）。

セットアップ:
  1. Telegram で @BotFather に /newbot → トークンを取得
  2. 環境変数を設定:
       export TELEGRAM_BOT_TOKEN="123456:ABC-DEF..."
       export TELEGRAM_ALLOWED_USERS="あなたのユーザーID"
     ※ ユーザーID確認: @userinfobot にメッセージを送る
  3. 起動:
       pip install python-telegram-bot
       python telegram_bot.py

コマンド:
  /start          — 使い方を表示
  /generate [数]  — 投稿を生成（デフォルト5件）
  /pending        — 未投稿の候補を表示
  /strategy       — 現在の運用戦略を表示
  /theme テーマ   — テーマを指定して生成
  テキスト送信    — そのテーマで投稿を生成
"""

import asyncio
import logging
import os
import subprocess
import sys
from pathlib import Path

from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

# ---------------------------------------------------------------------------
# 設定
# ---------------------------------------------------------------------------
BASE_DIR = Path(__file__).resolve().parent
GENERATE_SCRIPT = BASE_DIR / "generate_posts.sh"
STRATEGY_FILE = BASE_DIR / "x_strategy.md"
PENDING_FILE = BASE_DIR / "pending_posts.md"

BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
ALLOWED_USERS: set[int] = set()

_raw = os.environ.get("TELEGRAM_ALLOWED_USERS", "")
if _raw:
    for uid in _raw.split(","):
        uid = uid.strip()
        if uid.isdigit():
            ALLOWED_USERS.add(int(uid))

logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 認証チェック
# ---------------------------------------------------------------------------

def is_authorized(update: Update) -> bool:
    """許可されたユーザーかチェック"""
    if not ALLOWED_USERS:
        # 未設定の場合は全員許可（開発時用）
        return True
    user_id = update.effective_user.id if update.effective_user else None
    return user_id in ALLOWED_USERS


async def reject(update: Update) -> None:
    """未認証ユーザーへの応答"""
    await update.message.reply_text("このBotは許可されたユーザーのみ使用できます。")


# ---------------------------------------------------------------------------
# generate_posts.sh の実行
# ---------------------------------------------------------------------------

async def run_generate(count: int = 5, theme: str | None = None) -> str:
    """generate_posts.sh を非同期で実行し、出力を返す"""
    env = os.environ.copy()
    if theme:
        # 戦略ファイルの「今週の方針」セクションを一時的に上書き
        env["X_AGENT_THEME_OVERRIDE"] = theme

    cmd = [str(GENERATE_SCRIPT), str(count)]

    # シェルスクリプトの実行をブロッキングしないよう別スレッドで
    loop = asyncio.get_event_loop()
    try:
        result = await loop.run_in_executor(
            None,
            lambda: subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=300,  # 5分タイムアウト
                env=env,
            ),
        )
        output = result.stdout
        if result.returncode != 0:
            output += f"\n[ERROR] 終了コード: {result.returncode}\n{result.stderr}"
        return output
    except subprocess.TimeoutExpired:
        return "[ERROR] 生成がタイムアウトしました（5分）。"
    except Exception as e:
        return f"[ERROR] 実行エラー: {e}"


# ---------------------------------------------------------------------------
# コマンドハンドラー
# ---------------------------------------------------------------------------

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/start — 使い方を表示"""
    if not is_authorized(update):
        return await reject(update)

    text = (
        "X投稿生成Bot へようこそ!\n\n"
        "使い方:\n"
        "  /generate [数] — 投稿を生成（デフォルト5件）\n"
        "  /theme テーマ — テーマを指定して生成\n"
        "  /pending — 未投稿の候補を表示\n"
        "  /strategy — 現在の運用戦略を表示\n\n"
        "テキストを送るとそのテーマで投稿を生成します。"
    )
    await update.message.reply_text(text)


async def cmd_generate(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/generate [数] — 投稿を生成"""
    if not is_authorized(update):
        return await reject(update)

    count = 5
    if context.args:
        try:
            count = int(context.args[0])
            count = max(1, min(count, 20))
        except ValueError:
            pass

    await update.message.reply_text(f"投稿を {count}件 生成中... しばらくお待ちください。")
    output = await run_generate(count=count)
    # Telegram メッセージは4096文字制限
    for chunk in _split_message(output):
        await update.message.reply_text(chunk)


async def cmd_theme(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/theme テーマ — テーマを指定して生成"""
    if not is_authorized(update):
        return await reject(update)

    if not context.args:
        await update.message.reply_text("使い方: /theme バイブコーディング")
        return

    theme = " ".join(context.args)
    await update.message.reply_text(f"テーマ「{theme}」で投稿を生成中...")
    output = await run_generate(count=5, theme=theme)
    for chunk in _split_message(output):
        await update.message.reply_text(chunk)


async def cmd_pending(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/pending — 未投稿の候補を表示"""
    if not is_authorized(update):
        return await reject(update)

    if not PENDING_FILE.exists() or PENDING_FILE.stat().st_size == 0:
        await update.message.reply_text("未投稿の候補はありません。")
        return

    content = PENDING_FILE.read_text(encoding="utf-8")
    # 末尾2セクション分（最新の生成結果）を表示
    sections = content.split("\n## ")
    if len(sections) > 2:
        content = "## " + "\n## ".join(sections[-2:])

    for chunk in _split_message(content):
        await update.message.reply_text(chunk)


async def cmd_strategy(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/strategy — 現在の運用戦略を表示"""
    if not is_authorized(update):
        return await reject(update)

    if not STRATEGY_FILE.exists():
        await update.message.reply_text("[ERROR] 戦略ファイルが見つかりません。")
        return

    content = STRATEGY_FILE.read_text(encoding="utf-8")
    for chunk in _split_message(content):
        await update.message.reply_text(chunk)


async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """テキストメッセージ → そのテーマで投稿を生成"""
    if not is_authorized(update):
        return await reject(update)

    theme = update.message.text.strip()
    if not theme:
        return

    await update.message.reply_text(f"テーマ「{theme}」で投稿を生成中...")
    output = await run_generate(count=5, theme=theme)
    for chunk in _split_message(output):
        await update.message.reply_text(chunk)


# ---------------------------------------------------------------------------
# ユーティリティ
# ---------------------------------------------------------------------------

def _split_message(text: str, max_len: int = 4000) -> list[str]:
    """Telegram の文字数制限に合わせてメッセージを分割"""
    if len(text) <= max_len:
        return [text] if text.strip() else ["(出力なし)"]

    chunks = []
    while text:
        if len(text) <= max_len:
            chunks.append(text)
            break
        # 改行位置で分割
        split_at = text.rfind("\n", 0, max_len)
        if split_at == -1:
            split_at = max_len
        chunks.append(text[:split_at])
        text = text[split_at:].lstrip("\n")

    return chunks if chunks else ["(出力なし)"]


# ---------------------------------------------------------------------------
# メイン
# ---------------------------------------------------------------------------

def main() -> None:
    if not BOT_TOKEN:
        print(
            "[ERROR] 環境変数 TELEGRAM_BOT_TOKEN を設定してください。\n"
            "  1. Telegram で @BotFather に /newbot\n"
            "  2. 取得したトークンを設定:\n"
            "     export TELEGRAM_BOT_TOKEN='123456:ABC-DEF...'\n",
            file=sys.stderr,
        )
        sys.exit(1)

    if not ALLOWED_USERS:
        logger.warning(
            "TELEGRAM_ALLOWED_USERS が未設定です。全ユーザーがアクセス可能です。\n"
            "本番では必ず設定してください: export TELEGRAM_ALLOWED_USERS='あなたのID'"
        )

    logger.info("Telegram Bot を起動します...")
    logger.info("許可ユーザー: %s", ALLOWED_USERS or "(全員)")

    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("generate", cmd_generate))
    app.add_handler(CommandHandler("theme", cmd_theme))
    app.add_handler(CommandHandler("pending", cmd_pending))
    app.add_handler(CommandHandler("strategy", cmd_strategy))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
