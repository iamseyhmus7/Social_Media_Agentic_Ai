from datetime import datetime, timezone
from pathlib import Path
from sqlalchemy import create_engine, event, String, Text, Integer, Float, JSON, ForeignKey, Boolean, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker
from .config import settings


def now():
    return datetime.now(timezone.utc).timestamp()


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = 'users'
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    email: Mapped[str] = mapped_column(String(254), unique=True)
    name: Mapped[str] = mapped_column(String(100))
    password_hash: Mapped[str] = mapped_column(Text)
    role: Mapped[str] = mapped_column(String(10), default='member')
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    brand: Mapped[dict] = mapped_column(JSON, default=dict)


class Session(Base):
    __tablename__ = 'sessions'
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey('users.id'))
    csrf: Mapped[str] = mapped_column(String(64))
    expires: Mapped[float] = mapped_column(Float)


class Project(Base):
    __tablename__ = 'projects'
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey('users.id'), index=True)
    topic: Mapped[str] = mapped_column(Text)
    title: Mapped[str] = mapped_column(String(240))
    audience: Mapped[str] = mapped_column(String(300), default='Genel izleyici')
    tone: Mapped[str] = mapped_column(String(80), default='İlgi çekici ve bilgilendirici')
    duration: Mapped[int] = mapped_column(Integer, default=45)
    duration_auto: Mapped[bool] = mapped_column(Boolean, default=False, server_default='false')
    revision: Mapped[int] = mapped_column(Integer, default=1)
    created: Mapped[float] = mapped_column(Float, default=now)
    music_asset: Mapped[str | None] = mapped_column(String(36), nullable=True)


class Run(Base):
    __tablename__ = 'runs'
    __table_args__ = (UniqueConstraint('project_id', 'revision', name='uq_run_project_revision'),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    project_id: Mapped[str] = mapped_column(ForeignKey('projects.id'), index=True)
    user_id: Mapped[str] = mapped_column(ForeignKey('users.id'), index=True)
    active_owner: Mapped[str | None] = mapped_column(String(36), unique=True, nullable=True)
    revision: Mapped[int] = mapped_column(Integer)
    pipeline_version: Mapped[int] = mapped_column(Integer, default=1, server_default='1')
    status: Mapped[str] = mapped_column(String(32), default='queued')
    stage: Mapped[str] = mapped_column(String(40), default='supervisor')
    outputs: Mapped[dict] = mapped_column(JSON, default=dict)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    cancel_requested: Mapped[bool] = mapped_column(Boolean, default=False)
    created: Mapped[float] = mapped_column(Float, default=now)
    updated: Mapped[float] = mapped_column(Float, default=now)
    started: Mapped[float | None] = mapped_column(Float, nullable=True)
    finished: Mapped[float | None] = mapped_column(Float, nullable=True)


class Feedback(Base):
    __tablename__ = 'feedback_requests'
    __table_args__ = (UniqueConstraint('user_id', 'request_id', name='uq_feedback_request'),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey('users.id'), index=True)
    project_id: Mapped[str] = mapped_column(ForeignKey('projects.id'), index=True)
    source_run_id: Mapped[str] = mapped_column(ForeignKey('runs.id'))
    request_id: Mapped[str] = mapped_column(String(80))
    prompt: Mapped[str] = mapped_column(Text)
    answer: Mapped[str] = mapped_column(Text, default='')
    status: Mapped[str] = mapped_column(String(32), default='queued', index=True)
    decision: Mapped[dict] = mapped_column(JSON, default=dict)
    run_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created: Mapped[float] = mapped_column(Float, default=now)


class RemoteJob(Base):
    __tablename__ = 'remote_jobs'
    __table_args__ = (UniqueConstraint('run_id', 'input_hash', 'attempt', name='uq_remote_attempt'),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    run_id: Mapped[str] = mapped_column(ForeignKey('runs.id'), index=True)
    input_hash: Mapped[str] = mapped_column(String(64))
    attempt: Mapped[int] = mapped_column(Integer, default=0)
    kernel: Mapped[str] = mapped_column(String(200))
    version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[str] = mapped_column(String(32), default='prepared')
    account_slot: Mapped[str | None] = mapped_column(String(100), unique=True, nullable=True)
    next_poll: Mapped[float] = mapped_column(Float, default=0)
    created: Mapped[float] = mapped_column(Float, default=now)
    result: Mapped[dict] = mapped_column(JSON, default=dict)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)


class Event(Base):
    __tablename__ = 'events'
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(ForeignKey('runs.id'), index=True)
    stage: Mapped[str] = mapped_column(String(40))
    message: Mapped[str] = mapped_column(Text)
    created: Mapped[float] = mapped_column(Float, default=now)


class Asset(Base):
    __tablename__ = 'assets'
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    project_id: Mapped[str] = mapped_column(ForeignKey('projects.id'), index=True)
    run_id: Mapped[str | None] = mapped_column(ForeignKey('runs.id'), nullable=True)
    revision: Mapped[int] = mapped_column(Integer)
    kind: Mapped[str] = mapped_column(String(24))
    path: Mapped[str] = mapped_column(Text)
    mime: Mapped[str] = mapped_column(String(80))
    sha256: Mapped[str] = mapped_column(String(64))


class Approval(Base):
    __tablename__ = 'approvals'
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    run_id: Mapped[str] = mapped_column(ForeignKey('runs.id'), unique=True)
    user_id: Mapped[str] = mapped_column(ForeignKey('users.id'))
    manifest: Mapped[str] = mapped_column(String(64))
    created: Mapped[float] = mapped_column(Float, default=now)


class Publication(Base):
    __tablename__ = 'publications'
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    project_id: Mapped[str] = mapped_column(ForeignKey('projects.id'), index=True)
    run_id: Mapped[str] = mapped_column(ForeignKey('runs.id'), unique=True)
    status: Mapped[str] = mapped_column(String(30), default='queued')
    publish_at: Mapped[str | None] = mapped_column(String(40), nullable=True)
    made_for_kids: Mapped[bool] = mapped_column(Boolean, default=False)
    synthetic_media: Mapped[bool] = mapped_column(Boolean, default=True)
    upload_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    offset: Mapped[int] = mapped_column(Integer, default=0)
    video_id: Mapped[str | None] = mapped_column(String(80), nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)


class YouTubeConnection(Base):
    __tablename__ = 'youtube_connections'
    user_id: Mapped[str] = mapped_column(ForeignKey('users.id'), primary_key=True)
    encrypted_token: Mapped[str] = mapped_column(Text)


class OAuthState(Base):
    __tablename__ = 'oauth_states'
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey('users.id'))
    expires: Mapped[float] = mapped_column(Float)


class WorkerLease(Base):
    __tablename__ = 'worker_leases'
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    token: Mapped[str | None] = mapped_column(String(36), nullable=True)
    expires: Mapped[float] = mapped_column(Float, default=0)


cfg = settings()
if cfg.database_url.startswith('sqlite:///'):
    Path(cfg.database_url.removeprefix('sqlite:///')).parent.mkdir(parents=True, exist_ok=True)
engine = create_engine(cfg.database_url, connect_args={'check_same_thread': False, 'timeout': 30} if cfg.database_url.startswith('sqlite') else {}, pool_pre_ping=True)
if cfg.database_url.startswith('sqlite'):
    @event.listens_for(engine, 'connect')
    def sqlite_pragmas(conn, _):
        conn.execute('PRAGMA foreign_keys=ON')
        conn.execute('PRAGMA journal_mode=WAL')
DB = sessionmaker(engine, expire_on_commit=False)


def init_db():
    Base.metadata.create_all(engine)
    with DB() as db:
        if not db.get(WorkerLease, 1):
            db.add(WorkerLease(id=1, expires=0))
            db.commit()


def get_db():
    with DB() as db:
        yield db
