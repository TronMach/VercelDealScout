import asyncio
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient

from src import auth, crypto, db

BASE = 'http://localhost:5173'
STEAM_ID = '76561197960435530'


@pytest.fixture(autouse=True)
def env(tmp_path, monkeypatch):
    monkeypatch.setenv('SESSION_SECRET', 'test-secret')
    monkeypatch.setenv('APP_BASE_URL', BASE)
    monkeypatch.setenv('DATABASE_URL', f'sqlite+aiosqlite:///{tmp_path / "test.db"}')
    monkeypatch.setenv('ENCRYPTION_KEY', Fernet.generate_key().decode())
    crypto._fernet.cache_clear()
    yield
    crypto._fernet.cache_clear()


def assertion(nonce: str, **overrides) -> dict[str, str]:
    claimed = f'https://steamcommunity.com/openid/id/{STEAM_ID}'
    params = {
        'openid.ns': auth.OPENID_NS,
        'openid.mode': 'id_res',
        'openid.op_endpoint': auth.STEAM_OPENID_URL,
        'openid.claimed_id': claimed,
        'openid.identity': claimed,
        'openid.return_to': f'{BASE}{auth.CALLBACK_PATH}?state={nonce}',
        'openid.response_nonce': '2026-10-30T00:00:00Zabc',
        'openid.assoc_handle': '1234567890',
        'openid.signed': 'signed,op_endpoint,claimed_id,identity,return_to,response_nonce,assoc_handle',
        'openid.sig': 'c2lnbmF0dXJl',
    }
    params.update(overrides)
    return params


def steam_client(is_valid: bool, seen: list | None = None) -> httpx.AsyncClient:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == 'steamcommunity.com' and request.method == 'POST':
            if seen is not None:
                seen.append(parse_qs(request.content.decode()))
            return httpx.Response(200, text=f'ns:{auth.OPENID_NS}\nis_valid:{"true" if is_valid else "false"}\n')
        # Public profile XML
        return httpx.Response(200, text='<profile><steamID><![CDATA[Robin]]></steamID>'
                                        '<avatarFull><![CDATA[https://avatars.steamstatic.com/a_full.jpg]]></avatarFull></profile>')
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def test_valid_assertion_is_verified_with_steam():
    seen = []
    async def body():
        async with steam_client(True, seen) as client:
            return await auth.verify_login(client, assertion('n1'), BASE, 'n1')
    assert asyncio.run(body()) == STEAM_ID
    assert seen[0]['openid.mode'] == ['check_authentication']
    assert seen[0]['openid.sig'] == ['c2lnbmF0dXJl']


def test_steam_saying_invalid_is_rejected():
    async def body():
        async with steam_client(False) as client:
            await auth.verify_login(client, assertion('n1'), BASE, 'n1')
    with pytest.raises(auth.LoginError):
        asyncio.run(body())


@pytest.mark.parametrize('overrides, nonce', [
    ({'openid.return_to': f'https://evil.example{auth.CALLBACK_PATH}?state=n1'}, 'n1'),
    ({}, 'other-nonce'),
    ({'openid.claimed_id': 'https://evil.example/openid/id/76561197960435530'}, 'n1'),
    ({'openid.op_endpoint': 'https://evil.example/openid/login'}, 'n1'),
    ({'openid.identity': 'https://steamcommunity.com/openid/id/76561197960435531'}, 'n1'),
    ({'openid.signed': 'signed,op_endpoint,identity'}, 'n1'),
    ({'openid.mode': 'cancel'}, 'n1'),
])
def test_bad_assertions_are_rejected_before_asking_steam(overrides, nonce):
    with pytest.raises(auth.LoginError):
        auth.check_assertion_fields(assertion('n1', **overrides), BASE, nonce)


def test_session_round_trip_and_tamper():
    token = auth.make_session(STEAM_ID)
    assert auth.read_session(token) == STEAM_ID
    assert auth.read_session(token + 'x') is None
    assert auth.read_session(None) is None


@pytest.fixture
def app_client(monkeypatch):
    import server
    monkeypatch.setattr(server, 'get_client', lambda: steam_client(True))
    with TestClient(server.app, base_url=BASE) as client:
        yield client
    asyncio.run(db.dispose_engines())


def test_full_login_flow_sets_session_cookie(app_client):
    response = app_client.get('/api/auth/steam/login', follow_redirects=False)
    assert response.status_code == 302
    steam_url = urlsplit(response.headers['location'])
    assert f'{steam_url.scheme}://{steam_url.netloc}{steam_url.path}' == auth.STEAM_OPENID_URL
    return_to = parse_qs(steam_url.query)['openid.return_to'][0]
    nonce = parse_qs(urlsplit(return_to).query)['state'][0]

    callback = app_client.get(auth.CALLBACK_PATH, params=assertion(nonce), follow_redirects=False)
    assert callback.status_code == 302
    assert callback.headers['location'] == f'{BASE}/?signed_in=1'
    assert auth.SESSION_COOKIE in callback.cookies

    me = app_client.get('/api/auth/me')
    assert me.json() == {'steam_id': STEAM_ID, 'persona_name': 'Robin',
                         'avatar_url': 'https://avatars.steamstatic.com/a_full.jpg', 'discord_linked': False}


def test_callback_without_login_state_cookie_is_refused(app_client):
    callback = app_client.get(auth.CALLBACK_PATH, params=assertion('n1'), follow_redirects=False)
    assert 'login_error' in callback.headers['location']
    assert auth.SESSION_COOKIE not in callback.cookies


def test_signed_out_requests_get_401(app_client):
    assert app_client.get('/api/settings').status_code == 401
    assert app_client.get(f'/api/deals/wishlist/{STEAM_ID}').status_code == 401


def test_writes_from_another_origin_are_blocked(app_client):
    app_client.cookies.set(auth.SESSION_COOKIE, auth.make_session(STEAM_ID))
    blocked = app_client.put('/api/settings', json={}, headers={'Origin': 'https://evil.example'})
    assert blocked.status_code == 403
    not_json = app_client.put('/api/settings', content='steam_api_key=x',
                              headers={'Origin': BASE, 'Content-Type': 'application/x-www-form-urlencoded'})
    assert not_json.status_code == 415
