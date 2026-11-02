from fastapi.testclient import TestClient
from sqlalchemy import delete
from backend.app.main import app
from backend.app.db import DB, User
from backend.app.config import settings


def account(email='creator@example.test'):
    return {'email': email, 'name': 'İçerik Üreticisi', 'password': 'a-strong-password-123'}


def test_first_account_bootstrap_and_next_member(setup):
    with DB() as db:
        db.execute(delete(User))
        db.commit()
    with TestClient(app) as client:
        first = client.post('/api/v1/auth/register', json=account())
        assert first.status_code == 201
        assert first.json()['user']['role'] == 'admin'
        assert 'HttpOnly' in first.headers['set-cookie']
        assert client.get('/api/v1/auth/session').json()['user']['email'] == account()['email']
        second = client.post('/api/v1/auth/register', json=account('member@example.test'))
        assert second.status_code == 201
        assert second.json()['user']['role'] == 'member'
        # Registered sessions use the same CSRF protection as normal login.
        assert client.post('/api/v1/projects', json={'topic': 'Türkçe bir video konusu'}).status_code == 403
        client.headers['X-CSRF-Token'] = second.json()['csrf']
        assert client.post('/api/v1/projects', json={'topic': 'Türkçe bir video konusu'}).status_code == 201


def test_registration_validation_duplicate_and_role_injection(setup):
    with TestClient(app) as client:
        data = account()
        data['email'] = '  CREATOR@example.test  '
        registered = client.post('/api/v1/auth/register', json=data)
        assert registered.status_code == 201
        assert registered.json()['user']['role'] == 'member'
        assert registered.json()['user']['email'] == 'creator@example.test'
        assert client.post('/api/v1/auth/register', json=account()).status_code == 409
        assert client.post('/api/v1/auth/register', json={**account('admin2@example.test'), 'role': 'admin'}).status_code == 422
        for field, value in [('name', '   '), ('email', 'invalid'), ('password', 'short')]:
            assert client.post('/api/v1/auth/register', json={**account(), field: value}).status_code == 422
        assert client.post('/api/v1/auth/register', json=account('other@example.test'), headers={'Origin': 'https://evil.test'}).status_code == 403


def test_registration_disabled_and_rate_limited(setup, monkeypatch):
    with TestClient(app) as client:
        monkeypatch.setattr(settings(), 'allow_registration', False)
        assert client.post('/api/v1/auth/register', json=account()).status_code == 403
        monkeypatch.setattr(settings(), 'allow_registration', True)
        for i in range(5):
            assert client.post('/api/v1/auth/register', json=account(f'creator{i}@example.test')).status_code == 201
        assert client.post('/api/v1/auth/register', json=account('last@example.test')).status_code == 429
