# OrcaRouter 経由でモデル内蔵の Web 検索が使えるか（#47）

**本番構成は変更していない。** 独立したスクリプト
`backend/scripts/orca_websearch_check.py` で確かめた。

## 公式仕様（docs.orcarouter.ai）

**2 つの経路がある。どちらも公式に明記されている。**

| 経路 | 指定 | 仕様の記述 |
|---|---|---|
| Chat Completions | `web_search_options` | 「OpenAI search-preview モデル、modern web_search tool を受け付ける OpenAI モデル、および Anthropic モデル（Anthropic ネイティブの web_search server-tool へ変換）で有効」 |
| Chat Completions | `web_search`（生ペイロード） | 「`web_search_options` で表現しきれないとき、上流の web 検索ツールへそのまま転送」 |
| Responses API `POST /v1/responses` | `tools: [{"type":"web_search"}]` | 「built-in web grounding」。**「内蔵ツールの呼び出し（web_search_call 等）は 1 回ごとに課金される」と明記** |

カタログに `openai/gpt-5-search-api` / `openai/gpt-5-search-api-2025-10-14` が存在する（全 198 モデル中）。

## 実測（通常呼び出しと検索付き呼び出しを対で実行）

同じ質問「2026年10月に東京都内で現地参加できるハウス/テクノのクラブイベント 3 件。
開催日 / 会場 / 出典URL」を投げ、差を見た。

| # | 経路・モデル | 検索 | 結果 | 実費 |
|---|---|---|---|---|
| 1 | Chat / `openai/gpt-5` | なし | 引用 0 件・本文空（推論で枠を使い切り） | $0.009086 |
| 2 | Chat / `openai/gpt-5` | `web_search_options` | **HTTP 400 `upstream_rejected_request`** | — |
| 3 | Chat / `openai/gpt-5-search-api` | 指定なし | 引用 6 件（RA の URL） | $0.035958 |
| 4 | Chat / `openai/gpt-5-search-api` | `web_search_options` | 引用 3 件（RA の URL） | $0.047018 |
| 5 | Responses / `openai/gpt-5` | なし | `output` は `reasoning` のみ・本文空 | **不明** |
| 6 | Responses / `openai/gpt-5` | `tools:[{"type":"web_search"}]` | **`web_search_call` が 8 回**・本文あり | **不明** |

**結論: 対応している。** ただし条件がある。

- **`web_search_options` は任意の OpenAI モデルでは通らない。** `openai/gpt-5` では 400。
  `openai/gpt-5-search-api` では通る（#2 と #4 の差）。
- **`gpt-5-search-api` は指定しなくても検索する**（#3）。
  このモデルでは「通常呼び出し」と「検索付き呼び出し」が実質同じで、対照にならない。
  本当の対照は非検索モデル（#1）。
- **Responses API の `web_search` は `openai/gpt-5` で動く**（#6）。
  内蔵ツールの実行が `output` に `web_search_call` として現れるので、**検索したことを確認できる。**

## 出典照合（モデルの自己申告を信用しない）

#6 の出力 3 件を、こちらで取得して照合した。

| 主張 | 照合結果 |
|---|---|
| John Talabot / 10/3 / VENT / `livepocket.jp/e/vent_20261003` | **確認済み**（別途の診断で既に確認済みの出典と一致） |
| D.Dan / 10/11 / VENT / `livepocket.jp/e/vent_20261011` | **確認済み**（本文に D.Dan・10/11・2026・VENT すべて実在） |
| SECRET WEAPONS Ben Sims / 10/9 / CIRCUS TOKYO | **未確認**。当該ページを取得すると 1072 字しか返らず、`Ben Sims` はあるが日付が無い。**誤りとは言えない**（こちらの取得能力の問題の可能性） |

## 現行の「検索ツール付き構成」との違い

| | 内蔵検索（OrcaRouter 経由） | 現行の試作 v2（Serper + Jina をツールとして渡す） |
|---|---|---|
| 検索の実行 | 上流（OpenAI）の中。**どんな語で検索したかは見えない** | こちらのログに全部残る（今回 40 回の検索語すべて） |
| 取得本文 | **手元に残らない。** 引用 URL とモデルの要約だけ | **全文をディスクに保存**。あとから照合・再読ができる |
| RA（ja.ra.co） | **引用に出てくる**（#3 #4）。こちらの fetcher では取れない領域に届いている | Jina・httpx・Tavily すべてで取得不可。別出典へ回る必要がある |
| 費用の記録 | **Responses API は `usage.cost_usd` を返さない**（#5 #6 とも不明）。仕様上は内蔵ツール呼び出しが 1 回ごとに課金される | OrcaRouter の実費を全リクエストで記録（今回 $1.93、不明 0 件） |
| 件数の制御 | 会話 1 往復。**台帳も終了条件も無い** | 企画数・日程数で終了判定。停滞の記録も残る |
| Prompt Injection | 上流でページを読むため、**こちらの `guard` を通らない** | 取得本文は `guard.inspect` を通し、`untrusted_block` で囲む |

**いちばん効く差は RA への到達。** 参考20件のうち音楽10件は RA 由来で、
こちらの取得手段では本文を読めず、会場・チケット販売元へ回り込む必要があった。
内蔵検索はそこに直接届いている。

**いちばん困る差は費用記録と監査。** Responses API では実費が返らず、
検索語も取得本文も手元に残らない。「使用量記録と暴走防止を維持する」方針と噛み合わない。

## 今回使った費用

計測できた分の合計 **$0.092062**（#1 #3 #4）。
#5 #6 は `usage.cost_usd` が返らず**不明**。トークンは #5 が 1,220、#6 が 38,493。

## まだやっていないこと

- 内蔵検索を使った場合に、参考20件と同程度の**幅**（4 希望・20 日程）を出せるか
- Anthropic モデル経由の `web_search_options`（仕様上は対応と明記）
- 内蔵ツール課金の実額の確認手段（`/v1/cost` の settled cost で引けるか）
