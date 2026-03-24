#!/usr/bin/env bash
#
# X投稿生成の自動スケジュール設定
# crontab に登録して毎日自動で投稿候補を生成する
#
# 使い方:
#   ./setup_cron.sh              # デフォルト: 毎朝8時に5件生成
#   ./setup_cron.sh 07:00 3      # 毎朝7時に3件生成
#   ./setup_cron.sh remove       # スケジュール解除
#

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
GENERATE_SCRIPT="$SCRIPT_DIR/generate_posts.sh"
LOG_FILE="$SCRIPT_DIR/cron.log"
CRON_MARKER="# x_agent_auto_post"

if [[ "${1:-}" == "remove" ]]; then
    crontab -l 2>/dev/null | grep -v "$CRON_MARKER" | crontab -
    echo "[OK] 自動スケジュールを解除しました。"
    exit 0
fi

# 引数パース
TIME="${1:-08:00}"
COUNT="${2:-5}"
HOUR="${TIME%%:*}"
MINUTE="${TIME##*:}"

# バリデーション
if ! [[ "$HOUR" =~ ^[0-9]{1,2}$ ]] || ! [[ "$MINUTE" =~ ^[0-9]{1,2}$ ]]; then
    echo "[ERROR] 時刻の形式が不正です。HH:MM で指定してください（例: 08:00）" >&2
    exit 1
fi

# claude CLI のパスを解決
CLAUDE_PATH=$(command -v claude 2>/dev/null || true)
if [[ -z "$CLAUDE_PATH" ]]; then
    echo "[ERROR] claude CLI が見つかりません。" >&2
    exit 1
fi

# 既存のエントリを除去してから追加
EXISTING_CRON=$(crontab -l 2>/dev/null | grep -v "$CRON_MARKER" || true)
NEW_CRON="$MINUTE $HOUR * * * $GENERATE_SCRIPT $COUNT >> $LOG_FILE 2>&1 $CRON_MARKER"

echo "$EXISTING_CRON
$NEW_CRON" | crontab -

echo "============================================================"
echo " 自動スケジュールを設定しました"
echo "============================================================"
echo "  実行時刻: 毎日 ${HOUR}:${MINUTE}"
echo "  生成数:   ${COUNT}件"
echo "  ログ:     ${LOG_FILE}"
echo ""
echo "  確認:  crontab -l"
echo "  解除:  $0 remove"
echo "============================================================"
