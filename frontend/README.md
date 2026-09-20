# Frontend

React + TypeScript + Vite + Tailwind CSS。担当: 土居すみれ

```bash
npm install
cp .env.example .env
npm run dev      # http://localhost:5173
npm run lint
npm run build
```

画面のデザインは `opportunity-prototype/` のプロトタイプを移植したもの。
データはすべて `src/api/` 経由で Backend から取得する。

## Backend なしで開発する

`.env` で `VITE_USE_MOCK=true` にすると、Backend を呼ばず
`src/api/mock.ts` の Mock Data を返す。
**ホーム → 探索中 → 結果 → 詳細** まで Frontend 単体で確認できる。

Mock の中身は `backend/agent/stub_data.py` と揃えてある。
Mock の `GET /agent/runs/{id}` は最初から `completed` を返すため、
探索中の途中経過（ステップの進行）は Backend 接続時に確認する。

## 画面

| Route | 画面 |
| --- | --- |
| `/` | 会員登録前のホームページ（Backend を呼ばない紹介ページ） |
| `/app` | ② ホーム。いまのおすすめと探索の入り口 |
| `/app/explore` | ③ Agent 探索中（`?run_id=` を付けて遷移する） |
| `/app/results` | ④ Opportunity TOP3 |
| `/app/saved` | 気になる（`status: interested`） |
| `/app/steps` | 次の一歩（`status: registered` / `attended`） |

① プロフィール入力と ⑤ 詳細はダイアログ。
それぞれ `/app?edit=1` と `/app/results?detail={id}` で直接開ける。

移植前の URL はリダイレクトで残してある。

| 旧 | 新 |
| --- | --- |
| `/profile` | `/app?edit=1` |
| `/explore?run_id=` | `/app/explore?run_id=`（`run_id` は引き継ぐ） |
| `/opportunities` | `/app/results` |
| `/opportunities/:id` | `/app/results?detail=:id` |

## 構成

```
public/assets/     マスコットの画像（プロトタイプからそのまま）
src/
├── api/           Backend 呼び出し（client.ts が封筒の展開とエラー変換を行う）
│   └── mock.ts    Mock Data
├── types/         Backend の Schema と 1:1 対応する型
├── state/         5画面で共有する状態（プロフィール・一覧・status・ダイアログ）
├── pages/         上の表の各画面
├── components/
│   ├── welcome/   ホームページ
│   └── app/       アプリ本体（ヘッダー・サイドバー・カード・ダイアログ）
├── hooks/
├── styles/        スプライトとキーフレーム
└── utils/
    ├── date.ts    日時の表示
    ├── display.ts Opportunity をカード表現に落とす対応表
    └── poses.ts   スプライトの切り出し計算
```

## デザイン移植で決めたこと

**スタイルは Tailwind のユーティリティが中心。** 色・余白・字送りはプロトタイプの値を
そのまま arbitrary value（`text-[17px]` など）で書いている。CSS ファイルに残したのは
ユーティリティで書けないものだけ（キーフレーム、スプライトの背景計算、擬似要素）。

**Tailwind の Preflight は読み込んでいない。** 元のデザインは段落の余白・見出しの文字サイズを
ブラウザ既定値のまま使っており、Preflight はそれを消してしまう。
代わりに同じリセットを `src/index.css` に書いている。

**ブレークポイントは `@custom-variant`。** `lte1250:` `lte900:` `lte620:` などは
`@media (max-width: N)` に展開される。Tailwind 標準の `max-[640px]:` は
`640px 未満`になり、元の `640px 以下`とちょうど境界でズレるため使っていない。

**キャラクターは `public/assets/` の画像だけを使い、1画面に同じ絵を重複して置かない。**
静止ポーズは `poses-new.png`（418px 角の 3×3 に9枚）から配置ごとに別のコマを切り出す。
探索中の動きは `motion-*.png`（512px 角の 3×2 に6コマ）を `steps(1,end)` でコマ送りする。
再生するコマ画像は `AgentStep` ごとに変わる（`src/utils/poses.ts` の `MOTION_BY_STEP`）。

## Schema との対応

`src/types/` と `src/api/` は変更していない。表示に必要な対応づけは `src/utils/display.ts` に閉じている。

| 画面の表現 | 元のフィールド |
| --- | --- |
| カード上部の英字（`Build something.` など） | `type` ごとの固定文言。事実ではなく装飾 |
| `HACKATHON` などの分類 | `type` |
| `✧ 意外なつながり` | `serendipity_score >= 70` |
| 気になる | `status: interested`（`POST /opportunities/{id}/interest`） |
| 次の一歩 | `status: registered` / `attended` |

日時・場所・参加費は API の値をそのまま出し、`null` の項目は推測せず
「日時未定」「場所未定」「参加費未確認」と表示する。

## 既知の制約

- **「気になる」の解除**と**「次の一歩」への追加**に対応する API がまだ無い。
  そのぶんはこのブラウザの中だけで保持しており、リロードすると Backend の `status` に戻る。
  `POST /api/opportunities/{id}/calendar`（docs/api.md の 8）が実装されたら
  `src/state/AppStateProvider.tsx` の `markAsStep` をその結果に置き換える。
- **`status` は1つ**なので、「次の一歩」に進めた機会は「気になる」から外れる。
- 探索中の**一時停止は画面の更新を止めるだけ**で、Agent の実行は止まらない。
  実行を止める API が無いため。
- 一覧の Schema に `cost` が無いので、参加費は詳細ダイアログにだけ出る。

## 注意

- `src/types/` は Backend の Schema と 1:1。片方だけ変更しない
- 外部サービスへの登録は Agent が代行せず、登録ページへの誘導までにする
