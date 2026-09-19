# アーキテクチャ上の不変条件

詳細な図と説明は `docs/architecture.md`。ここには**守るべき制約だけ**を書く。

## レイヤの向き

```
api/routes/  →  services/  →  models/ (SQLAlchemy)
                    ↑
              agent/ → ai/ + tools/
```

- `api/routes/` に業務ロジックを書かない。薄く保ち `services/` へ委譲する。
- `services/` から HTTP の概念（status code / Request）を触らない。
- `models/`（SQLAlchemy）と `schemas/`（Pydantic）を混ぜない。
  API が返すのは必ず `schemas/` の型。

## 3 つのデータ分離

混同したら設計が壊れる。`docs/architecture.md` の表が正。

| | 例 | 出どころ |
| --- | --- | --- |
| Web 上の事実 | `start_at` `deadline` `location` `cost` | Tool |
| AI の評価 | `score` `reason` `serendipity_score` | LLM |
| ユーザーとの関係 | `status` | ユーザー操作 |

同様に **UserProfile（その人がどんな人か）** と
**Agent Memory（Agent がその人について学んだこと）** を分離する。
プロフィールを書き換えて学習結果を表現しない。

## Frontend / Backend の境界

境界は API 仕様（`docs/api.md`）。
`backend/schemas/*.py` と `frontend/src/types/*.ts` は 1:1 対応。**片方だけ変えない。**

Schema を変える手順は固定:
1. ユーザーへ共有（相方が使っている形式を勝手に変えない）
2. `docs/api.md` を更新
3. `backend/schemas/` と `frontend/src/types/` を同じコミットで直す
4. backend の pytest と frontend の build を両方通す

## 認証

MVP は認証なしの単一ユーザー（`models.DEFAULT_USER_ID`）。
認証を足すときは `backend/api/deps.py` の `current_user_id` だけ差し替える。
ここを前提にした `user_id` の引き回しを各所へ散らさない。

## 変えてよいもの / いけないもの

**勝手に変えない:** API エンドポイント、Request/Response、Pydantic Schema、
TypeScript の型、DB Schema、Agent Loop の構造、技術選定。

**自由に足してよい:** テスト、docstring、`services/` 内の実装、
`ai/prompts/`、`tools/` の中身、ログ出力（Secret を除く）。
