"""Technical completion hands the rendered video directly to its owner."""
from .providers import ProviderError


def enabled(run):
    return run.outputs.get('_config', {}).get('video_review_policy') == 'technical_only'


def technical_report(run):
    report = dict(run.outputs['editor']['report'])
    return {**report, 'method': 'technical_checks_human_content_review',
            'model_review_performed': False, 'requires_human_review': True,
            'summary': 'Teknik kontroller tamamlandı. İçerik ve kurgu kullanıcı incelemesini bekliyor.'}


def complete(run_id):
    from .pipeline import read, checkpoint, run_stage
    run, _, _ = read(run_id)
    report = technical_report(run)
    if not report.get('passed'):
        checkpoint(run_id, 'quality', report)
        raise ProviderError('Video teknik kontrolden geçmedi; mevcut render korundu. ' + ' '.join(report.get('issues', [])))
    if run.outputs.get('quality') != report:
        checkpoint(run_id, 'quality', report)
    # Packaging existing script and files is local; no model or publishing call.
    if 'publisher' not in run.outputs:
        run_stage(run_id, 'publisher')
