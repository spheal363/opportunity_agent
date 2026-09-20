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

Tailwind のユーティリティクラスを直接書く。新しい UI ライブラリを導入しない。

CSS ファイルは増やさない。ただし **Tailwind のユーティリティでは書けないもの**に限り
`src/styles/` に置いてよい。

- スプライトシートの切り出し（`background-size` と CSS 変数による位置指定）
- `@keyframes` と、コマ送りの `steps()`
- 擬似要素（`::before` / `::after` / `::backdrop`）

ユーティリティで書けるものをここに書かない。書いた CSS は `src/index.css` から import する。

**Tailwind の Preflight は読み込んでいない。** 画面のデザインは段落の余白と見出しの
文字サイズをブラウザ既定値のまま使っており、Preflight はそれを消してしまう。
同じ役割のリセットは `src/index.css` にある。戻さない。

## 変更後

```bash
npm run format && npm run lint && npm run build
```
