# Frontend

React + TypeScript + Vite + Tailwind CSS。担当: 土居すみれ

```bash
npm install
cp .env.example .env
npm run dev      # http://localhost:5173
npm run lint
npm run build
```

## Backend なしで開発する

`.env` で `VITE_USE_MOCK=true` にすると、Backend を呼ばず
`src/api/mock.ts` の Mock Data を返す。
**Profile → 探索中 → TOP3 → 詳細** まで Frontend 単体で確認できる。

Mock の中身は `backend/agent/stub_data.py` と揃えてある。

## 構成

```
src/
├── api/          Backend 呼び出し（client.ts が封筒の展開とエラー変換を行う）
│   └── mock.ts   Mock Data
├── types/        Backend の Schema と 1:1 対応する型
├── pages/        /profile /explore /opportunities /opportunities/:id
├── components/
├── hooks/
├── utils/
└── assets/
```

## 画面

| Route | 画面 |
| --- | --- |
| `/profile` | ① 初回プロフィール入力 |
| `/explore` | ③ Agent 探索中（`?run_id=` を付けて遷移する） |
| `/opportunities` | ④ Opportunity TOP3 |
| `/opportunities/:id` | ⑤ 詳細 / ⑥ 参加したい / ⑩ Feedback |

Calendar と Feedback は詳細画面の中から操作する。

現状の各画面は**動作確認用の最小実装**。UI / UX の作り込みは後続タスク。

## 注意

- `src/types/` は Backend の Schema と 1:1。片方だけ変更しない
- 外部サービスへの登録は Agent が代行せず、登録ページへの誘導までにする
