from uuid import uuid4
import os
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.schema import CreateSchema, DropSchema
from backend.app import db as dbmod
from backend.app.db import Base, DB, User, WorkerLease
from backend.app.config import settings
from backend.app.security import hasher
from backend.app.main import app, attempts


@pytest.fixture
def setup(tmp_path, monkeypatch):
    test_url = os.environ.get('TEST_DATABASE_URL')
    schema = None
    root_engine = None
    if test_url:
        root_engine = create_engine(test_url)
        if root_engine.dialect.name != 'postgresql':
            raise ValueError('TEST_DATABASE_URL must select PostgreSQL.')
        schema = 'test_' + uuid4().hex
        with root_engine.begin() as connection:
            connection.execute(CreateSchema(schema))
        engine = root_engine.execution_options(schema_translate_map={None: schema})
    else:
        engine = create_engine('sqlite:///' + str(tmp_path / 'test.db'), connect_args={'check_same_thread': False})
    original = dbmod.engine
    monkeypatch.setattr(dbmod, 'engine', engine)
    DB.configure(bind=engine)
    Base.metadata.create_all(engine)
    monkeypatch.setattr(settings(), 'media_root', tmp_path / 'media')
    monkeypatch.setattr(settings(), 'queue_mode', 'local')
    monkeypatch.setattr(settings(), 'evren_api_key', '')
    monkeypatch.setattr(settings(), 'evren_contract_verified', False)
    for key in ('youtube_api_key', 'rss_feeds', 'elevenlabs_api_key', 'cloudflare_api_token',
                'pexels_api_key','pixabay_api_key','unsplash_access_key','unsplash_secret_key',
                'openverse_client_id','openverse_client_secret'):
        monkeypatch.setattr(settings(), key, '')
    attempts.clear()
    with DB() as db:
        db.add(WorkerLease(id=1, expires=0))
        db.add_all([User(id='alice', email='alice@example.test', name='Alice', role='admin', password_hash=hasher.hash('test-password-123')), User(id='bob',email='bob@example.test',name='Bob',role='member',password_hash=hasher.hash('test-password-123'))])
        db.commit()
    yield tmp_path
    DB.configure(bind=original)
    engine.dispose()
    if root_engine is not None:
        with root_engine.begin() as connection:
            connection.execute(DropSchema(schema, cascade=True))
        root_engine.dispose()


@pytest.fixture
def clients(setup):
    with TestClient(app) as alice, TestClient(app) as bob:
        for client, email in [(alice,'alice@example.test'),(bob,'bob@example.test')]:
            response = client.post('/api/v1/auth/login', json={'email':email,'password':'test-password-123'})
            assert response.status_code == 200
            client.headers['X-CSRF-Token'] = response.json()['csrf']
        yield alice, bob


@pytest.fixture
def project(clients):
    alice, _ = clients
    result=alice.post('/api/v1/projects',json={'topic':'Kapadokya hakkında bir video hazırla','duration':45})
    assert result.status_code==201
    return result.json()
