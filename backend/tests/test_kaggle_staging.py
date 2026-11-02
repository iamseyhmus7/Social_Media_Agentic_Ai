from types import SimpleNamespace
import pytest
from backend.kaggle.generate import stage_model


def test_model_staging_preserves_nested_weights_and_uses_bounded_reads(tmp_path, monkeypatch):
    from backend.kaggle import generate
    source, target = tmp_path / 'input', tmp_path / 'scratch/model'
    (source / 'text_encoder').mkdir(parents=True)
    (source / 'text_encoder/config.json').write_text('{"model_type":"t5"}')
    weight = source / 'text_encoder/weights.safetensors'
    weight.write_bytes(b'owned-test-weight' * 100)
    monkeypatch.setattr(generate.shutil, 'disk_usage', lambda _: SimpleNamespace(free=10 * 1024**3))
    sizes = []
    original = generate.shutil.copyfileobj
    def bounded(reader, writer, length):
        sizes.append(length)
        return original(reader, writer, length)
    monkeypatch.setattr(generate.shutil, 'copyfileobj', bounded)
    assert stage_model(source, target) == target
    assert (target / 'text_encoder/weights.safetensors').read_bytes() == weight.read_bytes()
    assert (target / 'text_encoder/config.json').read_text() == '{"model_type":"t5"}'
    assert sizes and max(sizes) <= 8 * 1024**2
    assert not list(target.rglob('*.partial'))


def test_model_staging_checks_capacity_before_copy(tmp_path, monkeypatch):
    from backend.kaggle import generate
    source = tmp_path / 'input'; source.mkdir()
    (source / 'weights.safetensors').write_bytes(b'weight')
    monkeypatch.setattr(generate.shutil, 'disk_usage', lambda _: SimpleNamespace(free=1024))
    with pytest.raises(RuntimeError, match='scratch space'):
        stage_model(source, tmp_path / 'scratch/model')
    assert not (tmp_path / 'scratch/model').exists()
