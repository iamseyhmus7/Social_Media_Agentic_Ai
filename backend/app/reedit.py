"""Create an independent edit revision from verified owned media, without generation."""
from copy import deepcopy
import json
import shutil
from uuid import uuid4
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from .db import Run, Asset, Publication, Event
from .storage import check_disk, workdir, media_path, file_hash


def create_reedit(db, project, user, request, *, commit=True, preserve_editor=False):
    source = db.get(Run, request.run_id)
    if not source or source.project_id != project.id or source.user_id != user.id:
        raise HTTPException(404, 'Kaynak üretim bulunamadı.')
    paused_video = (source.status == 'waiting_input' and source.outputs.get('editor', {}).get('video')
        and not source.outputs.get('clarification', {}).get('question') and not source.active_owner)
    if source.revision != project.revision or (source.status in ('queued', 'running', 'waiting_remote', 'waiting_input') and not paused_video):
        raise HTTPException(409, 'Yalnızca durdurulmuş veya tamamlanmış güncel sürüm yeniden kurgulanabilir.')
    if source.pipeline_version < 2 or source.outputs.get('motion', {}).get('mode') != 'video':
        raise HTTPException(409, 'Yeniden kurgu için doğrulanmış hareketli klipler gerekli.')
    if not all(source.outputs.get(k) for k in ('script', 'voice', 'visual', 'motion')):
        raise HTTPException(409, 'Kaynak üretimin ses ve görsel aşamaları tamamlanmamış.')
    publication = db.scalar(select(Publication).where(Publication.run_id == source.id))
    if publication and (publication.status in ('uploading', 'uncertain') or publication.video_id):
        raise HTTPException(409, 'Yayınlanan veya yükleme sonucu belirsiz sürüm yeniden kurgulanamaz.')
    check_disk()
    retained = deepcopy({k: v for k, v in source.outputs.items() if k in (
        'supervisor', 'strategy', 'script', 'voice', 'visual', 'motion', '_config', '_brand', '_voice_plan')})
    retained.update(_edit_style=request.style, _edit_only=True, _edit_source_run=source.id)
    retained['_edit_preferences'] = {'instructions': request.instructions, 'map_intro': request.map_intro, 'show_sources': request.show_sources}
    run = Run(id=str(uuid4()), project_id=project.id, user_id=user.id, active_owner=user.id,
              revision=project.revision + 1, pipeline_version=2, stage='editor', outputs=deepcopy(retained))
    created, folder = [], None
    try:
        db.add(run)
        db.flush()  # Claim the unique active-owner slot before copying any files.
        folder = workdir(project.id, run.id)
        copied = {}

        def clone(asset_id, filename=None):
            if asset_id in copied:
                return copied[asset_id]
            original = db.get(Asset, asset_id)
            if not original or original.project_id != project.id:
                raise HTTPException(409, 'Kaynak medya bu projeye ait değil.')
            path = media_path(original.path)
            target = folder / (filename or ('reuse-' + original.id + path.suffix))
            if not target.resolve().is_relative_to(folder.resolve()):
                raise HTTPException(409, 'Geçersiz medya referansı.')
            shutil.copyfile(path, target)
            created.append(target)
            if file_hash(target) != original.sha256:
                raise HTTPException(409, 'Kaynak medya özeti değişmiş; yeniden kurgu durduruldu.')
            asset = Asset(id=str(uuid4()), project_id=project.id, run_id=run.id, revision=run.revision,
                          kind=original.kind, path=target.relative_to(media_path('')).as_posix(),
                          mime=original.mime, sha256=original.sha256)
            db.add(asset)
            copied[asset_id] = asset.id
            return asset.id

        retained['voice']['audios'] = [clone(i) for i in retained['voice']['audios']]
        retained['visual']['images'] = [clone(i) for i in retained['visual']['images']]
        if retained['visual'].get('shot_images'):
            retained['visual']['shot_images'] = {key: clone(value) for key, value in retained['visual']['shot_images'].items()}
        retained['visual']['cover'] = clone(retained['visual']['cover'])
        if preserve_editor and source.outputs.get('editor'):
            retained['editor'] = deepcopy(source.outputs['editor'])
            for key in ('video', 'subtitle'):
                retained['editor'][key] = clone(retained['editor'][key])
            retained['quality'] = deepcopy(source.outputs.get('quality', {}))
        for shot in retained['motion']['plan']['shots']:
            item = retained['motion']['clips'][shot['shot_id']]
            filename = shot['shot_id'] + '.mp4'
            item['asset_id'] = clone(item['asset_id'], filename)
            item['file'] = filename
        # A previously verified transcript cache can survive a style-only edit.
        old_folder = media_path(f'{project.id}/{source.id}')
        decisions = old_folder / 'edit-decisions-v4.json'
        if decisions.is_file() and decisions.stat().st_size <= 4_000_000:
            baseline = json.loads(decisions.read_text(encoding='utf-8'))
            baseline['durations'] = retained['voice']['durations']
            baseline['source_hashes'] = {key: db.get(Asset, clip['asset_id']).sha256
                for key, clip in retained['motion']['clips'].items()}
            target = folder / 'edit-source-decisions.json'
            target.write_text(json.dumps(baseline, ensure_ascii=False), encoding='utf-8')
            created.append(target)
        for name in ('captions.srt', 'captions.words.json', 'captions.cache.json'):
            if (old_folder / name).is_file():
                shutil.copyfile(old_folder / name, folder / name)
                created.append(folder / name)
        project.revision = run.revision
        run.outputs = deepcopy(retained)
        if publication:
            publication.status = 'cancelled'
        db.add(Event(run_id=run.id, stage='editor', message='Ses ve doğrulanmış klipler korunarak yeni kurgu sürümü oluşturuldu.'))
        if commit:
            db.commit()
        return run
    except Exception as exc:
        db.rollback()
        for item in created:
            item.unlink(missing_ok=True)
        if folder and folder.exists() and not any(folder.iterdir()):
            folder.rmdir()
        if isinstance(exc, IntegrityError):
            raise HTTPException(409, 'Başka bir üretimin zaten aktif.') from None
        raise

