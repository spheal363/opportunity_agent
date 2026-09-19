# 開発フロー / Branch Strategy

このページが Branch / Commit / Merge ルールの**正本**。
他のドキュメントはここを参照し、内容を複製しない。

## 基本方針

**「1 チケット = 1 ブランチ」にしない。**

```
1 つのまとまった機能  =  1 ブランチ
1 チケット            =  1 commit
```

ハッカソン期間中の開発速度と、2 人での並行開発を優先する。
チケットごとにブランチと PR を切ると、レビューと merge の往復だけで時間が溶ける。

## Branch

| Branch | 用途 |
| --- | --- |
| `main` | 常に動作可能・デモ可能な状態を維持する |
| `feature/<feature-name>` | 新機能 |
| `fix/<fix-name>` | バグ修正 |

**`main` 上で直接機能開発をしない。**

関連の強い複数チケットは 1 つの feature branch にまとめてよい。

```
feature/llm-integration
  #14 OrcaRouter接続
  #15 LLM共通処理

feature/web-search
  #16 Web Search Tool
  #17 Web Page Tool
  #18 Search結果→Opportunity構造化

feature/agent-loop
  #19 Agent Loop
  #20 Goal Analysis組み込み
  #21 Evaluation組み込み
  #22 再探索・終了条件
```

## Commit

チケットの作業境界は **commit で残す**。番号を必ず入れる。

```
feat: integrate OrcaRouter (#14)
feat: add shared LLM client (#15)
fix: handle empty search results (#16)
```

prefix は以下を使う。

```
feat:      新機能
fix:       バグ修正
refactor:  リファクタリング
docs:      ドキュメント
test:      テスト
chore:     設定・環境変更
style:     整形のみ（機能変更なし）
```

完璧な commit 履歴を作ることより、**何を変更した commit か分かること**を優先する。

## Merge

feature branch 上で以下の順に進める。

```
1. 実装
2. lint / test
3. code review          @agent-code-reviewer
4. security review      @agent-security-reviewer（必要に応じて）
5. PR
6. main へ merge
```

lint / test は Stop hook が変更領域だけ自動実行する（`.claude/hooks/verify.sh`）。

security review が**必要な変更**:

- `backend/agent/` `backend/ai/` `backend/tools/` を触った
- 外部データ（Web / 外部 API）を扱う経路を追加・変更した
- Tool の権限、承認フロー、Secret、環境変数を触った

PR 本文には最低限これを書く（`.github/pull_request_template.md`）。

```
## What   何を実装したか
## Test   どう確認したか
## Note   注意点・未実装部分
```

### merge しない状態

- アプリが起動しない
- Build が通らない
- 主要 API が壊れている
- Frontend が表示できない
- Secret が含まれている

### 例外

**緊急の軽微なドキュメント修正には、この運用を強制しない。**
typo、リンク切れ、実装状況の表の更新などは `main` へ直接 commit してよい。
コードに触る変更は例外にしない。

## 並行開発

Naoya と土居さんが**同じ feature branch を共有して同時に開発しない。**
担当領域ごとに branch を分け、`main` を統合点とする。

```
Naoya    feature/llm-integration ─┐
                                  ├─→ main
土居さん  feature/opportunity-ui ─┘
```

基本担当:

| | 領域 |
| --- | --- |
| Naoya | `backend/`、Agent Runtime、API、DB、Tools、OrcaRouter、Security、Infra |
| 土居さん | `frontend/`、AI Prompt、AI 評価ロジック、UX、Calendar UI |

共通で触る可能性が高いもの（`README.md`、`docker-compose.yml`、共通 Schema、API 仕様）は
**変更前に共有する。**

## 事前共有が必要な変更

以下は merge 前ではなく、**実装前**にもう一人へ共有する。

- API Endpoint / Request / Response
- UserProfile / Opportunity / AI の Schema
- DB Schema
- Agent Loop の構造
- 技術選定

手順は `①共有 → ②docs 更新 → ③backend と frontend を同時に修正`。

## Code Freeze

**9/22 10:00 以降は原則として新機能を追加しない。**

行うのは Bug Fix、デモ安定化、UI 微調整、発表準備のみ。
新しいアイデアが出ても、デモに必須でなければ実装しない。
