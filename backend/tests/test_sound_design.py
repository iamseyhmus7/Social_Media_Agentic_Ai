import wave
import pytest


def test_original_sound_design_is_deterministic_and_never_clips(tmp_path):
    np=pytest.importorskip('numpy')
    from backend.app.sound_design import create_sound_design
    first=tmp_path/'first.wav';second=tmp_path/'second.wav'
    for path in (first,second):create_sound_design(1,[0,.5,10],path)
    assert first.read_bytes()==second.read_bytes()
    with wave.open(str(first),'rb') as wav:
        assert wav.getframerate()==24000 and wav.getnframes()==24000 and wav.getnchannels()==1
        samples=np.frombuffer(wav.readframes(24000),dtype='<i2')
        assert 100<np.abs(samples).max()<8192
        assert abs(int(samples[-1]))<10
