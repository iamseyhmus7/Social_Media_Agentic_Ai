import argparse
import getpass
from uuid import uuid4
from cryptography.fernet import Fernet
from sqlalchemy import select
from .db import DB, User, init_db
from .security import hasher


def main():
    parser = argparse.ArgumentParser(description='Sahne yerel yönetim araçları')
    sub = parser.add_subparsers(dest='command', required=True)
    sub.add_parser('init-db')
    sub.add_parser('generate-key')
    sub.add_parser('check-evren')
    sub.add_parser('doctor')
    create = sub.add_parser('create-admin')
    create.add_argument('--email', required=True)
    create.add_argument('--name', default='Yönetici')
    args = parser.parse_args()
    if args.command == 'generate-key':
        print(Fernet.generate_key().decode())
        return
    if args.command == 'check-evren':
        from .providers import Evren, ProviderError
        from .schemas import Plan
        try:
            Evren(timeout=45).generate(Plan, 'Supervisor bağlantı testi', {'topic': 'Türkçe API bağlantı testi', 'instruction': 'Hedefi bağlantı doğrulaması olan çok kısa bir plan ve tek kontrol maddesi üret.'})
            print('Evren bağlantısı ve şemaya uygun JSON yanıtı doğrulandı.')
        except ProviderError as exc:
            raise SystemExit(str(exc)) from None
        return
    if args.command == 'doctor':
        import importlib.util
        import shutil
        from sqlalchemy import text
        from .config import settings
        from .db import engine
        cfg = settings()
        print('Veritabanı motoru:', engine.dialect.name)
        try:
            with engine.connect() as connection:
                connection.execute(text('SELECT 1'))
            print('Veritabanı bağlantısı: başarılı')
        except Exception:
            print('Veritabanı bağlantısı: başarısız; sunucu ve .env ayarlarını kontrol et.')
        print('Kuyruk modu:', cfg.queue_mode)
        print('Evren ayarları:', 'hazır' if cfg.evren_api_key and cfg.evren_base_url and cfg.evren_model and cfg.evren_contract_verified and cfg.evren_protocol == 'openai_chat' else 'eksik')
        print('Görsel sağlayıcısı:', cfg.image_provider)
        print('Cloudflare ayarları:', 'hazır' if cfg.cloudflare_account_id and cfg.cloudflare_api_token else 'eksik')
        print('Ses sağlayıcısı:', cfg.tts_provider)
        print('ElevenLabs ayarları:', 'hazır' if cfg.elevenlabs_api_key and (cfg.elevenlabs_voice_source == 'api' or cfg.elevenlabs_voice_id or cfg.elevenlabs_voice_profiles) else 'eksik')
        print('Ses kaynağı:', cfg.elevenlabs_voice_source)
        print('Karar modeli:', cfg.evren_model)
        print('FFmpeg / ffprobe:', bool(shutil.which(cfg.ffmpeg_bin) and shutil.which(cfg.ffprobe_bin)))
        print('Medya paketleri:', {m: importlib.util.find_spec(m) is not None for m in ['torch', 'diffusers', 'faster_whisper']})
        return
    init_db()
    if args.command == 'create-admin':
        password = getpass.getpass('Parola (en az 12 karakter): ')
        if len(password) < 12 or password != getpass.getpass('Parola tekrar: '):
            raise SystemExit('Parola uzunluğu veya tekrarı geçersiz.')
        with DB() as db:
            if db.scalar(select(User).where(User.email == args.email.strip().lower())):
                raise SystemExit('Bu e-posta zaten kayıtlı.')
            db.add(User(id=str(uuid4()), email=args.email.strip().lower(), name=args.name, role='admin', password_hash=hasher.hash(password)))
            db.commit()
        print('Yönetici oluşturuldu. Web arayüzünden giriş yapabilirsin.')
    else:
        print('Veritabanı hazır.')


if __name__ == '__main__':
    main()
