import asyncio
import json
import time

import httpx
import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
from nacl.signing import SigningKey

from src import crypto, db, deals_service, discord_app

BASE = 'http://localhost:5173'
STEAM_ID = '76561197960435530'
DISCORD_ID = '123456789012345678'
SIGNING_KEY = SigningKey.generate()


@pytest.fixture(autouse=True)
def env(tmp_path, monkeypatch):
    monkeypatch.setenv('SESSION_SECRET', 'test-secret')
    monkeypatch.setenv('APP_BASE_URL', BASE)
    monkeypatch.setenv('DATABASE_URL', f'sqlite+aiosqlite:///{tmp_path / "test.db"}')
    monkeypatch.setenv('ENCRYPTION_KEY', Fernet.generate_key().decode())
    monkeypatch.setenv('DISCORD_PUBLIC_KEY', SIGNING_KEY.verify_key.encode().hex())
    crypto._fernet.cache_clear()
    yield
    crypto._fernet.cache_clear()


def signed_headers(body: bytes, key: SigningKey = SIGNING_KEY) -> dict:
    timestamp = str(int(time.time()))
    signature = key.sign(timestamp.encode() + body).signature.hex()
    return {'X-Signature-Ed25519': signature, 'X-Signature-Timestamp': timestamp, 'Content-Type': 'application/json'}


def command(name: str, **options) -> dict:
    return {
        'type': discord_app.APPLICATION_COMMAND, 'application_id': '42', 'token': 'tok',
        'member': {'user': {'id': DISCORD_ID}},
        'data': {'name': name, 'options': [{'name': k, 'value': v} for k, v in options.items()]},
    }


@pytest.fixture
def client(monkeypatch):
    import server
    started = []
    async def fake_start(base, work):
        started.append(work)
    monkeypatch.setattr(server, 'start_discord_work', fake_start)
    with TestClient(server.app, base_url=BASE) as test_client:
        test_client.started = started
        yield test_client
    asyncio.run(db.dispose_engines())


def post(client, payload: dict, key: SigningKey = SIGNING_KEY):
    body = json.dumps(payload).encode()
    return client.post('/api/discord/interactions', content=body, headers=signed_headers(body, key))


def test_signature_check_with_generated_keypair():
    body = b'{"type":1}'
    headers = signed_headers(body)
    public = SIGNING_KEY.verify_key.encode().hex()
    assert discord_app.verify_signature(public, headers['X-Signature-Ed25519'], headers['X-Signature-Timestamp'], body)
    assert not discord_app.verify_signature(public, headers['X-Signature-Ed25519'], headers['X-Signature-Timestamp'], b'{"type":2}')
    assert not discord_app.verify_signature(public, 'not-hex', headers['X-Signature-Timestamp'], body)


def test_ping_gets_pong(client):
    assert post(client, {'type': 1}).json() == {'type': 1}


def test_bad_or_missing_signature_gets_401(client):
    assert post(client, {'type': 1}, key=SigningKey.generate()).status_code == 401
    assert client.post('/api/discord/interactions', json={'type': 1}).status_code == 401


def test_link_replies_privately_with_one_time_url(client):
    data = post(client, command('link')).json()
    assert data['type'] == discord_app.CHANNEL_MESSAGE
    assert data['data']['flags'] == discord_app.EPHEMERAL
    url = data['data']['components'][0]['components'][0]['url']
    assert url.startswith(f'{BASE}/api/auth/steam/login?link=')


def test_wishlist_when_not_linked_explains_link(client):
    data = post(client, command('wishlist')).json()
    assert data['data']['flags'] == discord_app.EPHEMERAL
    assert '/link' in data['data']['content']
    assert client.started == []


def test_wishlist_when_linked_defers_and_starts_work(client):
    async def setup():
        await db.upsert_user(STEAM_ID, 'Robin')
        await db.set_keys(STEAM_ID, deals_api_key='DEALSKEY')
        code = await db.create_link_code(DISCORD_ID)
        await db.redeem_link_code(code, STEAM_ID)
        await db.dispose_engines()
    asyncio.run(setup())

    data = post(client, command('wishlist', max_price=5, sort='price')).json()
    assert data == {'type': discord_app.DEFERRED_CHANNEL_MESSAGE}
    assert client.started[0]['options'] == {'max_price': 5, 'sort': 'price'}
    assert client.started[0]['token'] == 'tok'

    # /library needs a Steam key too
    data = post(client, command('library')).json()
    assert 'Steam API key' in data['data']['content']


def test_work_endpoint_needs_the_secret(client):
    assert client.post('/api/discord/work', json={}).status_code == 403


def make_result(count: int) -> dict:
    deals = [deals_service.add_deal_fields({
        'appid': i, 'name': f'Game [{i}]' + 'x' * 80, 'url': f'https://gg.deals/game/{i}/', 'image_url': '',
        'currency': 'USD',
        'prices': {'retail_price': 19.99, 'retail_price_low': 0.0, 'keyshop_price': 4.99, 'keyshop_price_low': 0.0},
    }) for i in range(count)]
    return {'kind': 'wishlist', 'steam_id': STEAM_ID, 'max_price': 10.0, 'sort': 'found', 'games_total': count,
            'games_scanned': count, 'rate_limited': False, 'stats': deals_service.summarize(deals), 'deals': deals}


def test_pages_fit_discord_limits_and_buttons_disable_at_ends():
    result = make_result(25)
    first = discord_app.render_page(result, 'abcdef0123456789', 0, BASE, 'Robin')
    embed = first['embeds'][0]
    total_chars = len(embed['title']) + len(embed['description']) + len(embed['footer']['text'])
    assert total_chars < 6000 and len(first['embeds']) <= 10
    assert embed['footer']['text'].startswith('Page 1/3')
    prev_btn, next_btn, open_btn = first['components'][0]['components']
    assert prev_btn['disabled'] is True and next_btn['custom_id'] == 'pg:abcdef0123456789:1'
    assert open_btn['url'] == BASE

    last = discord_app.render_page(result, 'abcdef0123456789', 2, BASE, 'Robin')
    assert last['components'][0]['components'][1]['disabled'] is True
    assert last['embeds'][0]['description'].count('\n**') == 4  # 5 deals on the last page


def test_do_work_scans_saves_and_edits_the_reply(monkeypatch):
    edits = []
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == 'PATCH'
        assert request.url.path == '/api/v10/webhooks/42/tok/messages/@original'
        edits.append(json.loads(request.content))
        return httpx.Response(200, json={})

    async def fake_scan(kind, steam_id, steam, dealsgg, max_price, sort):
        assert (kind, steam_id, max_price, sort) == ('wishlist', STEAM_ID, 5.0, 'price')
        assert dealsgg.api_key == 'DEALSKEY'
        return make_result(12)
    monkeypatch.setattr(deals_service, 'scan', fake_scan)

    async def body():
        await db.upsert_user(STEAM_ID, 'Robin')
        await db.set_keys(STEAM_ID, deals_api_key='DEALSKEY')
        code = await db.create_link_code(DISCORD_ID)
        await db.redeem_link_code(code, STEAM_ID)
        work = {'application_id': '42', 'token': 'tok', 'command': 'wishlist',
                'options': {'max_price': 5, 'sort': 'price'}, 'discord_user_id': DISCORD_ID}
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            await discord_app.do_work(work, BASE, http)

        # The ▶ button shows page 2 from the saved scan
        next_id = edits[0]['components'][0]['components'][1]['custom_id']
        page = await discord_app.handle_component({'data': {'custom_id': next_id}}, BASE)
        await db.dispose_engines()
        return page

    page = asyncio.run(body())
    assert edits[0]['embeds'][0]['title'] == 'Wishlist deals for Robin under $10.00'  # from the (fake) scan result
    assert edits[0]['embeds'][0]['footer']['text'].startswith('Page 1/2')
    assert page['type'] == discord_app.UPDATE_MESSAGE
    assert page['data']['embeds'][0]['footer']['text'].startswith('Page 2/2')
