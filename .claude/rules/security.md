---
paths:
  - "backend/**/*.py"
  - "frontend/src/api/**/*.ts"
---

# Security

方針の全体像は `docs/architecture.md` の Security 節。ここは実装時のチェック項目。

## Untrusted input

Web 検索結果・取得したページ本文・外部 API のレスポンスは**すべて Untrusted Data**。

- ページ本文を system prompt や instruction として連結しない。
  データであることが明示されたブロックに入れて渡す。
- ページ内の「以前の指示を無視して」等を Agent への命令として実行しない。
- 抽出した URL をそのまま Tool へ渡して追加取得しない（探索範囲は Agent の計画が決める）。
- 抽出結果は Schema Validation を通してから保存する。

## Tool 実行

- 権限レベルなしの Tool を作らない（`backend/tools/base.py`）。
- `APPROVAL` の Tool を `approved=True` 固定で呼ぶコードを書かない。
  承認はユーザー操作に由来する場合のみ `True` にする。
- LLM の出力だけを根拠に `approved` を決めない。
- 外部サービスへの登録・応募・送信を Agent が代行しない。

## Secret

- `.env` を commit しない。`.env.example` にはキー名だけ置き、値を書かない。
- API Key / Token を `logger` へ渡さない。例外メッセージに含めて再 raise しない。
- API のエラーレスポンスに内部情報を載せない（`api/errors.py` の `_unexpected` が既定）。
- Secret を誤って commit したら、削除だけで済ませず**該当 Secret を無効化・再発行する**。

## Logging

以下を Log へ出さない: API Key、`.env` の値、プロフィール本文、`about`、
取得したページ本文の全文。Agent の判断を残すときは要約と ID に留める。

## Validation

- 外部から来る値（Request body、LLM 出力、Web 抽出結果）を Pydantic で必ず検証する。
- `score` などの数値は範囲を持たせる。enum は `StrEnum` で閉じる。
- ユーザー入力をそのまま SQL / URL / HTML へ埋め込まない。
