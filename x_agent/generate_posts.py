#!/usr/bin/env python3
"""
X投稿生成スクリプト — 2エージェント構成
========================================
Opus（司令塔）: 戦略ファイルを読み、投稿の方向性・テーマ・トーンを指示
Sonnet（実行役）: Opusの指示に従い、具体的な投稿文を複数生成

使い方:
    export ANTHROPIC_API_KEY="sk-ant-..."
    python generate_posts.py [--count 5]
"""

import argparse
import csv
import json
import os
import sys
from datetime import datetime
from pathlib import Path

import anthropic

# ---------------------------------------------------------------------------
# 定数
# ---------------------------------------------------------------------------
OPUS_MODEL = "claude-opus-4-6"
SONNET_MODEL = "claude-sonnet-4-6"

BASE_DIR = Path(__file__).resolve().parent
STRATEGY_FILE = BASE_DIR / "x_strategy.md"
PENDING_FILE = BASE_DIR / "pending_posts.md"
POST_LOG_FILE = BASE_DIR / "post_log.csv"

# ---------------------------------------------------------------------------
# ユーティリティ
# ---------------------------------------------------------------------------

def read_strategy() -> str:
    """戦略ファイルを読み込む"""
    if not STRATEGY_FILE.exists():
        print(f"[ERROR] 戦略ファイルが見つかりません: {STRATEGY_FILE}", file=sys.stderr)
        sys.exit(1)
    return STRATEGY_FILE.read_text(encoding="utf-8")


def read_recent_posts(n: int = 20) -> str:
    """直近の投稿ログを読み込む（重複回避用）"""
    if not POST_LOG_FILE.exists():
        return "（過去の投稿ログはまだありません）"

    rows: list[str] = []
    with open(POST_LOG_FILE, encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows.append(row.get("post_content", ""))

    recent = rows[-n:] if len(rows) > n else rows
    if not recent:
        return "（過去の投稿ログはまだありません）"
    return "\n".join(f"- {p}" for p in recent)


# ---------------------------------------------------------------------------
# Agent 1: Opus — 司令塔
# ---------------------------------------------------------------------------

OPUS_SYSTEM = """\
あなたはX（旧Twitter）運用の司令塔AIです。
与えられた運用戦略と過去の投稿ログを分析し、
次に生成すべき投稿の「指示書」を作成してください。

指示書には以下を含めてください：
1. 今回のテーマ（戦略の投稿テーマから選択）
2. 投稿スタイル（実況型／共感型／発見型 から選択）
3. トーン・口調の指定
4. 盛り込むべきキーワードや要素
5. 避けるべきこと（過去投稿との重複など）
6. 各投稿の簡単な方向性メモ（1投稿につき1行）

出力は日本語のMarkdownで、簡潔に。
"""


def run_opus(client: anthropic.Anthropic, strategy: str, recent_posts: str, count: int) -> str:
    """Opus に投稿方針を考えさせる"""
    print("[Opus] 戦略を分析し、投稿指示書を作成中...")

    user_prompt = f"""\
## 運用戦略
{strategy}

## 直近の投稿（重複回避用）
{recent_posts}

## 依頼
上記の戦略に基づき、これから生成する **{count}件** の投稿について
指示書を作成してください。
バリエーションを持たせ、過去の投稿と重複しないようにしてください。
"""

    response = client.messages.create(
        model=OPUS_MODEL,
        max_tokens=2048,
        system=OPUS_SYSTEM,
        messages=[{"role": "user", "content": user_prompt}],
    )
    directive = response.content[0].text
    print("[Opus] 指示書の作成が完了しました。\n")
    return directive


# ---------------------------------------------------------------------------
# Agent 2: Sonnet — 実行役
# ---------------------------------------------------------------------------

SONNET_SYSTEM = """\
あなたはX（旧Twitter）の投稿文を作成するAIライターです。
司令塔AIから受け取った指示書に従い、投稿文を生成してください。

ルール：
- 1投稿は140文字以内（日本語）を目安にする
- 自然な話し言葉で、親しみやすいトーンにする
- ハッシュタグは1〜2個まで
- 各投稿はJSON配列で出力する

出力フォーマット（これだけを出力）:
```json
[
  {
    "content": "投稿本文",
    "theme": "テーマ名",
    "style": "スタイル名"
  }
]
```
"""


def run_sonnet(client: anthropic.Anthropic, directive: str, count: int) -> list[dict]:
    """Sonnet に具体的な投稿文を生成させる"""
    print("[Sonnet] 指示書に基づき投稿文を生成中...")

    user_prompt = f"""\
## 司令塔AIからの指示書
{directive}

## 依頼
上記の指示書に厳密に従い、**{count}件** の投稿文をJSON配列で出力してください。
コードブロックなしの純粋なJSONのみを出力してください。
"""

    response = client.messages.create(
        model=SONNET_MODEL,
        max_tokens=4096,
        system=SONNET_SYSTEM,
        messages=[{"role": "user", "content": user_prompt}],
    )

    raw = response.content[0].text.strip()

    # JSON部分を抽出（コードブロックで囲まれている場合に対応）
    if "```" in raw:
        lines = raw.split("\n")
        json_lines = []
        inside = False
        for line in lines:
            if line.strip().startswith("```"):
                inside = not inside
                continue
            if inside:
                json_lines.append(line)
        raw = "\n".join(json_lines)

    posts = json.loads(raw)
    print(f"[Sonnet] {len(posts)}件の投稿文を生成しました。\n")
    return posts


# ---------------------------------------------------------------------------
# 結果の保存
# ---------------------------------------------------------------------------

def save_to_pending(posts: list[dict]) -> None:
    """pending_posts.md に追記"""
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    lines = [f"\n## 生成日時: {now}\n"]
    for i, post in enumerate(posts, 1):
        lines.append(f"### 投稿 {i}")
        lines.append(f"- **テーマ**: {post.get('theme', 'N/A')}")
        lines.append(f"- **スタイル**: {post.get('style', 'N/A')}")
        lines.append(f"- **本文**: {post['content']}")
        lines.append("")

    with open(PENDING_FILE, "a", encoding="utf-8") as f:
        f.write("\n".join(lines))

    print(f"[保存] {PENDING_FILE.name} に{len(posts)}件を追記しました。")


# ---------------------------------------------------------------------------
# メイン
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="X投稿生成スクリプト（Opus司令塔 + Sonnet実行役）")
    parser.add_argument("--count", type=int, default=5, help="生成する投稿数（デフォルト: 5）")
    args = parser.parse_args()

    # APIキー確認
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("[ERROR] 環境変数 ANTHROPIC_API_KEY を設定してください。", file=sys.stderr)
        sys.exit(1)

    client = anthropic.Anthropic()

    # 1. 入力データの準備
    strategy = read_strategy()
    recent_posts = read_recent_posts()

    # 2. Opus（司令塔）: 投稿方針を策定
    directive = run_opus(client, strategy, recent_posts, args.count)
    print("=" * 60)
    print("📋 Opus 指示書:")
    print("=" * 60)
    print(directive)
    print("=" * 60)

    # 3. Sonnet（実行役）: 投稿文を生成
    posts = run_sonnet(client, directive, args.count)

    # 4. 結果を表示
    print("=" * 60)
    print("✏️  生成された投稿:")
    print("=" * 60)
    for i, post in enumerate(posts, 1):
        print(f"\n[{i}] {post['content']}")
        print(f"    テーマ: {post.get('theme', 'N/A')} / スタイル: {post.get('style', 'N/A')}")

    # 5. pending_posts.md に保存
    save_to_pending(posts)

    print("\n[完了] 投稿候補の生成が完了しました。")
    print(f"  → {PENDING_FILE} を確認し、投稿するものを選んでください。")


if __name__ == "__main__":
    main()
