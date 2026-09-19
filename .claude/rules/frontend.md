---
paths:
  - "frontend/**/*.ts"
  - "frontend/**/*.tsx"
  - "frontend/**/*.css"
---

# Frontend の書き方

画面一覧と Mock の使い方は `frontend/README.md`。

## 必ず守る

- **API 呼び出しは `src/api/` 経由。** コンポーネントから `fetch` を直接呼ばない。
  封筒の展開とエラー変換は `src/api/client.ts` に集約されている。
- **`src/types/` は `backend/schemas/` と 1:1。** 片方だけ変えない（`architecture.md` の手順に従う）。
- **`USE_MOCK` 分岐は `src/api/` の中だけ。** 画面側に持ち込まない。
  Mock の内容は `backend/agent/stub_data.py` と揃える。
- **日時は `src/utils/date.ts` の `formatDateTime` で表示する。** Backend は UTC で返す。
  `new Date(...).toLocaleString()` を直書きしない。
- **外部サービスへの登録・個人情報送信を自動実行しない。** 登録ページへの誘導までに留める
  （製品の設計思想。`CLAUDE.md` の Product を参照）。

## スタイル

Tailwind のユーティリティクラスを直接書く。CSS ファイルを増やさない。
新しい UI ライブラリを導入しない。

## 変更後

```bash
npm run format && npm run lint && npm run build
```
