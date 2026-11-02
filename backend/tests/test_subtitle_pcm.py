"""Regression for PyAV API mismatches; run in the media worker environment."""
import sys
from types import SimpleNamespace
import wave

import pytest


def test_subtitles_passes_normalized_pcm_to_whisper(monkeypatch, tmp_path):
    np = pytest.importorskip('numpy')
    pytest.importorskip('huggingface_hub')
    from backend.app import media
    observed = []
    class Model:
        def __init__(self, *args, **kwargs):
            assert kwargs['local_files_only'] is True
        def transcribe(self, audio, **kwargs):
            assert isinstance(audio, np.ndarray)
            assert audio.dtype == np.float32
            assert audio.max() <= 1
            observed.append(audio)
            return [SimpleNamespace(words=[SimpleNamespace(word='Merhaba', start=0.0, end=0.5)])], None
    monkeypatch.setitem(sys.modules, 'faster_whisper', SimpleNamespace(WhisperModel=Model))
    def convert(args, cwd, check_cancel):
        with wave.open(str(cwd / 'asr-input.wav'), 'wb') as wav:
            wav.setparams((1, 2, 16000, 0, 'NONE', 'none'))
            wav.writeframes(b'\x00\x40' * 16000)
    monkeypatch.setattr(media, 'command', convert)
    (tmp_path / 'voice.wav').write_bytes(b'source-audio')
    target = tmp_path / 'captions.srt'
    assert media.subtitles([tmp_path / 'voice.wav'], [1], target, lambda: None) == 1
    assert media.subtitles([tmp_path / 'voice.wav'], [1], target, lambda: None) == 1
    assert len(observed) == 1  # Verified cache avoids repeat transcription.
    assert observed[0][0] == 0.5
    assert 'Merhaba' in target.read_text()
    assert not (tmp_path / 'asr-input.wav').exists()

