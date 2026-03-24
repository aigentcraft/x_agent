#!/usr/bin/env bash
#
# X投稿生成スクリプト — 2エージェント構成（Claude Code CLI版）
# =============================================================
# Opus（司令塔）: 戦略を読み、投稿の方向性を指示
# Sonnet（実行役）: 指示に従い投稿文を生成
#
# Max Plan 定額内で動作（APIキー不要）
#
# 使い方:
#   chmod +x generate_posts.sh
#   ./generate_posts.sh [投稿数]     # デフォルト: 5
#

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
STRATEGY_FILE="$SCRIPT_DIR/x_strategy.md"
PENDING_FILE="$SCRIPT_DIR/pending_posts.md"
POST_LOG_FILE="$SCRIPT_DIR/post_log.csv"
COUNT="${1:-5}"

# --- 前提チェック ---
if ! command -v claude &>/dev/null; then
    echo "[ERROR] claude CLI が見つかりません。Claude Code をインストールしてください。" >&2
    exit 1
fi

if [[ ! -f "$STRATEGY_FILE" ]]; then
    echo "[ERROR] 戦略ファイルが見つかりません: $STRATEGY_FILE" >&2
    exit 1
fi

# --- 直近の投稿ログを取得（重複回避用）---
RECENT_POSTS="（過去の投稿ログはまだありません）"
if [[ -f "$POST_LOG_FILE" ]]; then
    # ヘッダー行を除いた直近20件の post_content 列を取得
    BODY=$(tail -n +2 "$POST_LOG_FILE" | tail -20 | cut -d',' -f3 | sed 's/^/- /')
    if [[ -n "$BODY" ]]; then
        RECENT_POSTS="$BODY"
    fi
fi

STRATEGY=$(cat "$STRATEGY_FILE")

# --- テーマ上書き（Telegram Bot からの指定）---
THEME_OVERRIDE="${X_AGENT_THEME_OVERRIDE:-}"
if [[ -n "$THEME_OVERRIDE" ]]; then
    STRATEGY="${STRATEGY}

## 今回の指定テーマ（最優先）
ユーザーから「${THEME_OVERRIDE}」というテーマが指定されました。
このテーマを中心に投稿を生成してください。"
fi

echo "============================================================"
echo " X投稿生成スクリプト（Claude Code CLI版）"
echo " Opus = 司令塔 / Sonnet = 実行役"
echo " 生成数: ${COUNT}件"
echo "============================================================"
echo ""

# ======================================================================
# Agent 1: Opus（司令塔）— 投稿指示書を作成
# ======================================================================
echo "[Opus] 戦略を分析し、投稿指示書を作成中..."

DIRECTIVE=$(cat <<PROMPT | claude -p --model opus
あなたはX（旧Twitter）運用の司令塔AIです。
以下の運用戦略と過去の投稿ログを分析し、次に生成すべき投稿の「指示書」を作成してください。

指示書には以下を含めてください：
1. 今回のテーマ（戦略の投稿テーマから選択）
2. 投稿スタイル（実況型／共感型／発見型 から選択）
3. トーン・口調の指定
4. 盛り込むべきキーワードや要素
5. 避けるべきこと（過去投稿との重複など）
6. 各投稿の簡単な方向性メモ（1投稿につき1行）

## 運用戦略
${STRATEGY}

## 直近の投稿（重複回避用）
${RECENT_POSTS}

## 依頼
上記の戦略に基づき、これから生成する ${COUNT}件 の投稿について指示書を作成してください。
バリエーションを持たせ、過去の投稿と重複しないようにしてください。
出力は日本語のMarkdownで、簡潔に。
PROMPT
)

echo ""
echo "============================================================"
echo " Opus 指示書:"
echo "============================================================"
echo "$DIRECTIVE"
echo "============================================================"
echo ""

# ======================================================================
# Agent 2: Sonnet（実行役）— 具体的な投稿文を生成
# ======================================================================
echo "[Sonnet] 指示書に基づき投稿文を生成中..."

POSTS_JSON=$(cat <<PROMPT | claude -p --model sonnet
あなたはX（旧Twitter）の投稿文を作成するAIライターです。
司令塔AIから受け取った指示書に従い、投稿文を生成してください。

ルール：
- 1投稿は140文字以内（日本語）を目安にする
- 自然な話し言葉で、親しみやすいトーンにする
- ハッシュタグは1〜2個まで
- 純粋なJSON配列のみを出力（コードブロック不要、説明不要）

## 司令塔AIからの指示書
${DIRECTIVE}

## 依頼
上記の指示書に厳密に従い、${COUNT}件 の投稿文をJSON配列で出力してください。
フォーマット: [{"content":"投稿本文","theme":"テーマ名","style":"スタイル名"}, ...]
JSONのみ出力。他のテキストは一切不要。
PROMPT
)

echo ""
echo "============================================================"
echo " 生成された投稿:"
echo "============================================================"

# --- JSONから投稿を抽出して表示 ---
# コードブロックが含まれていたら除去
CLEAN_JSON=$(echo "$POSTS_JSON" | sed '/^```/d')

echo "$CLEAN_JSON" | python3 -c "
import sys, json
raw = sys.stdin.read().strip()
try:
    posts = json.loads(raw)
except json.JSONDecodeError:
    print('[ERROR] JSONのパースに失敗しました。生の出力:')
    print(raw)
    sys.exit(1)

for i, p in enumerate(posts, 1):
    print(f\"  [{i}] {p['content']}\")
    print(f\"      テーマ: {p.get('theme','N/A')} / スタイル: {p.get('style','N/A')}\")
    print()
"

# --- pending_posts.md に追記 ---
NOW=$(date '+%Y-%m-%d %H:%M')

echo "$CLEAN_JSON" | python3 -c "
import sys, json

raw = sys.stdin.read().strip()
posts = json.loads(raw)
now = '${NOW}'

lines = [f'\n## 生成日時: {now}\n']
for i, p in enumerate(posts, 1):
    lines.append(f'### 投稿 {i}')
    lines.append(f'- **テーマ**: {p.get(\"theme\", \"N/A\")}')
    lines.append(f'- **スタイル**: {p.get(\"style\", \"N/A\")}')
    lines.append(f'- **本文**: {p[\"content\"]}')
    lines.append('')

print('\n'.join(lines))
" >> "$PENDING_FILE"

echo "============================================================"
echo "[保存] pending_posts.md に追記しました。"
echo "[完了] 投稿候補の生成が完了しました。"
echo "  → $PENDING_FILE を確認し、投稿するものを選んでください。"
