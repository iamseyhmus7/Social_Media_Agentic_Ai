import hashlib
import secrets
from argon2 import PasswordHasher
from argon2.exceptions import VerificationError, InvalidHashError
from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session as DBSession
from .db import get_db, Session, User, now

hasher = PasswordHasher()


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def current_user(request: Request, db: DBSession = Depends(get_db)):
    token = request.cookies.get('sahne_session', '')
    session = db.get(Session, digest(token))
    if not session or session.expires < now():
        raise HTTPException(401, 'Oturum açmalısın.')
    user = db.get(User, session.user_id)
    if not user or not user.active:
        raise HTTPException(401, 'Hesap etkin değil.')
    if request.method not in ('GET', 'HEAD', 'OPTIONS'):
        supplied = request.headers.get('X-CSRF-Token', '')
        if not secrets.compare_digest(session.csrf, supplied):
            raise HTTPException(403, 'Geçersiz CSRF doğrulaması.')
    request.state.session = session
    return user


def admin(user=Depends(current_user)):
    if user.role != 'admin':
        raise HTTPException(403, 'Yönetici erişimi gerekli.')
    return user


def verify_password(password, encoded):
    try:
        return hasher.verify(encoded, password)
    except (VerificationError, InvalidHashError):
        return False
