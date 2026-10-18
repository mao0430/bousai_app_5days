from uuid import uuid4

import app as app_module
from app import app, parse_area_warnings


def test_shelter_register_post_registers_new_shelter():
    client = app.test_client()
    with client.session_transaction() as sess:
        sess['logged_in'] = True
        sess['username'] = 'admin'

    shelter_name = f'テスト避難所_{uuid4().hex[:8]}'
    response = client.post('/shelter_register', data={'name': shelter_name})
    body = response.get_data(as_text=True)

    assert response.status_code == 200
    assert '避難所を登録しました。' in body


def test_shelter_register_keeps_capacity_and_occupancy_info_visible():
    client = app.test_client()
    with client.session_transaction() as sess:
        sess['logged_in'] = True
        sess['username'] = 'admin'

    shelter_name = f'収容数テスト避難所_{uuid4().hex[:8]}'
    response = client.post(
        '/shelter_register',
        data={
            'name': shelter_name,
            'address': '青森市テスト町1-2-3',
            'status': '開設中',
            'capacity': '120',
            'current_occupants': '80',
        }
    )
    body = response.get_data(as_text=True)

    assert response.status_code == 200
    assert '避難所を登録しました。' in body

    list_response = client.get('/all_shelters')
    list_body = list_response.get_data(as_text=True)

    assert list_response.status_code == 200
    assert '収容人数' in list_body
    assert '現在の避難者数' in list_body
    assert '空き状況' in list_body
    assert '120' in list_body
    assert '80' in list_body


def test_shelter_amenities_are_registered_and_shown_as_comparable_icons():
    client = app.test_client()
    with client.session_transaction() as sess:
        sess['logged_in'] = True
        sess['username'] = 'admin'

    shelter_name = f'設備テスト避難所_{uuid4().hex[:8]}'
    response = client.post(
        '/shelter_register',
        data={
            'name': shelter_name,
            'address': '青森市テスト町4-5-6',
            'pet_allowed': 'on',
            'barrier_free': 'on',
        }
    )
    try:
        assert response.status_code == 200
        assert '避難所を登録しました。' in response.get_data(as_text=True)

        list_response = client.get('/all_shelters')
        list_body = list_response.get_data(as_text=True)

        assert list_response.status_code == 200
        assert '設備・対応' in list_body
        assert 'ペット同伴' in list_body
        assert 'バリアフリー' in list_body
        assert '車いす対応トイレ' in list_body
        assert '福祉スペース' in list_body
        assert '対応あり' in list_body
        assert '対応なし' in list_body
    finally:
        app_module.shelters[:] = [
            shelter for shelter in app_module.shelters
            if shelter.get('name') != shelter_name
        ]
        app_module.save_shelters()


def test_empty_shelter_search_shows_message_and_change_conditions_button():
    client = app.test_client()
    response = client.get('/search_results?district=条件外')
    body = response.get_data(as_text=True)

    assert response.status_code == 200
    assert '条件に合う避難所がありません' in body
    assert '検索画面に戻る' in body
    assert 'href="/shelter_search"' in body

    search_response = client.get('/shelter_search')
    search_body = search_response.get_data(as_text=True)
    assert search_response.status_code == 200
    assert 'pet_allowed' in search_body
    assert 'barrier_free' in search_body
    assert 'wheelchair_toilet' not in search_body
    assert 'welfare_space' not in search_body


def test_return_navigation_is_fixed_and_available_on_every_page():
    client = app.test_client()
    pages = (
        '/',
        '/shelter_search',
        '/search_results?pet_allowed=on&barrier_free=on'
        '&wheelchair_toilet=on&welfare_space=on',
        '/all_shelters',
        '/login',
    )

    for page in pages:
        response = client.get(page)
        body = response.get_data(as_text=True)

        assert response.status_code == 200
        assert 'class="return-toolbar"' in body
        assert '検索画面に戻る' in body
        assert 'トップページへ戻る' in body
        assert 'position: fixed' in body
        assert 'inset: auto 0 0' in body


def test_parse_area_warnings_matches_jma_aomori_city_codes():
    payload = [{
        'reportDatetime': '2026-10-18T09:00:00+09:00',
        'warning': {
            'class10Items': [
                {'areaCode': '020010', 'kinds': [{'code': '15', 'status': '発表'}]},
                {'areaCode': '020020', 'kinds': [{'status': '発表警報・注意報はなし'}]}
            ],
            'class20Items': [
                {'areaCode': '0220100', 'kinds': [{'code': '15', 'status': '発表'}]},
                {'areaCode': '0220200', 'kinds': [{'status': '発表警報・注意報はなし'}]}
            ]
        }
    }]

    warnings, latest = parse_area_warnings(payload)

    assert latest == '2026-10-18T09:00:00+09:00'
    assert warnings and any(w['code'] == '15' for w in warnings)
