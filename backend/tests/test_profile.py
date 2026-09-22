# 画面（frontend/src/api/client.ts）が付けるヘッダー。状態を変える API に必須（#80）
PAGE = {"X-Requested-With": "opportunity-agent"}


def test_profile_missing_returns_not_found(client):
    res = client.get("/api/profile")
    assert res.status_code == 404
    assert res.json()["error"]["code"] == "NOT_FOUND"


def test_profile_upsert_and_get(client, profile_payload):
    res = client.put("/api/profile", json=profile_payload, headers=PAGE)
    assert res.status_code == 200
    assert res.json()["data"]["user_id"]

    res = client.get("/api/profile")
    assert res.status_code == 200
    data = res.json()["data"]
    assert data["name"] == "Naoya"
    assert data["skills"] == profile_payload["skills"]


def test_a_profile_without_a_name_is_accepted(client):
    """**名前は任意**（初回フォームを 4 項目にした、#47）。"""
    res = client.put(
        "/api/profile",
        json={"wants_now": "音楽イベントに行きたい", "location": "オンライン"},
        headers=PAGE,
    )
    assert res.status_code == 200

    data = client.get("/api/profile").json()["data"]
    assert data["wants_now"] == "音楽イベントに行きたい"
    assert data["location"] == "オンライン"


def test_profile_validation_error(client):
    res = client.put("/api/profile", json={"name": 123}, headers=PAGE)  # 型が違う
    assert res.status_code == 422
    assert res.json()["error"]["code"] == "VALIDATION_ERROR"


# --- 初回フォームを 4 項目にした（#47）-------------------------------------


def test_the_four_field_form_does_not_erase_the_old_input(client):
    """**フォームから外した項目を消さない。**

    以前のフォームは興味タグ・立場・できること・自己紹介も送っていた。
    4 項目だけ送るようになっても、既存データは残す。
    """
    client.put(
        "/api/profile",
        json={
            "name": "旧",
            "interests": ["AI", "Startup"],
            "occupation": "エンジニア",
            "skills": ["Python"],
            "about": "自己紹介の本文",
            "goals": ["将来は起業したい"],
        },
        headers=PAGE,
    )
    # 新しいフォームが送るのは 4 項目だけ。
    client.put(
        "/api/profile",
        json={
            "name": "新",
            "wants_now": "ポケモンのイベントに行きたい",
            "future_goals": "将来の起業",
            "location": "東京",
        },
        headers=PAGE,
    )

    data = client.get("/api/profile").json()["data"]
    assert data["wants_now"] == "ポケモンのイベントに行きたい"
    assert data["interests"] == ["AI", "Startup"], "興味タグが消えている"
    assert data["about"] == "自己紹介の本文", "自己紹介が消えている"
    assert data["occupation"] == "エンジニア"


def test_a_saved_profile_survives_a_round_trip(client):
    """保存して開き直しても、本文が変わらない。**改行も保つ。**"""
    text = "ハウス/テクノのイベント\n曲作りのワークショップ\nポケモンのイベント"
    client.put("/api/profile", json={"name": "N", "wants_now": text}, headers=PAGE)

    assert client.get("/api/profile").json()["data"]["wants_now"] == text


def test_the_legacy_goals_are_shown_in_the_main_field(client, db_session=None):
    """**旧データを推測で分割・書き換えしない。**

    `wants_now` がまだ無いプロフィールでは、以前の `goals` を行のまま
    本文として見せる。編集画面で内容が消えないようにするため。
    """
    client.put(
        "/api/profile",
        json={"name": "旧", "goals": ["音楽イベントに行きたい", "将来は起業したい"]},
        headers=PAGE,
    )

    data = client.get("/api/profile").json()["data"]
    assert data["wants_now"] == "音楽イベントに行きたい\n将来は起業したい"
    # **勝手に「将来」へ振り分けない。** 本人が編集して決める。
    assert data["future_goals"] is None
