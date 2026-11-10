"""Speech-triggered ducking and deterministic sound effects."""
import wave


def music_mix_filters(voice, music, duration, *, voice_gain=1, music_gain=.18):
    """Normalize inputs, then duck the music using the actual narration envelope."""
    end = max(0,duration-1.2)
    return [f'{voice}loudnorm=I=-16:TP=-2:LRA=7,aresample=48000,volume={voice_gain},asplit=2[voice][duckvoice]',
        f'{music}loudnorm=I=-18:TP=-3:LRA=7,aresample=48000,highpass=f=80,lowpass=f=8500,'
        f'volume={min(.25,max(0,music_gain))},afade=t=in:d=0.12,afade=t=out:st={end}:d=1.2[musicbed]',
        '[musicbed][duckvoice]sidechaincompress=threshold=0.025:ratio=8:attack=15:release=280:makeup=1[music]']


def create_cue_sound_design(duration, cues, target):
    """Only authored cue windows contain sound; pauses remain silent."""
    import numpy as np
    rate = 24000
    audio = np.zeros(round(duration * rate), dtype=np.float64)
    rng = np.random.default_rng(20261026)
    for cue in cues:
        start = round(cue['start_frame'] / 30 * rate)
        size = min(round(cue['frames'] / 30 * rate), len(audio)-start)
        if size <= 0:
            continue
        t = np.arange(size) / rate
        envelope = np.sin(np.pi * np.arange(size) / max(1, size-1)) ** 2
        if cue['kind'] == 'whoosh':
            noise = rng.standard_normal(size)
            signal = np.convolve(noise, np.ones(9)/9, mode='same')
        elif cue['kind'] == 'tick':
            signal = np.sin(2*np.pi*1100*t) * np.exp(-35*t)
        else:
            signal = np.sin(2*np.pi*(85*t-25*t*t)) * np.exp(-9*t)
        audio[start:start+size] += cue['gain'] * envelope * signal
    pcm = np.rint(np.clip(audio, -.25, .25) * 32767).astype('<i2')
    with wave.open(str(target), 'wb') as wav:
        wav.setparams((1, 2, rate, 0, 'NONE', 'none'))
        wav.writeframes(pcm.tobytes())


def create_sound_design(duration, cues, target):
    import numpy as np
    rate = 24000
    t = np.arange(round(duration * rate), dtype=np.float64) / rate
    rng = np.random.default_rng(20261026)
    audio = np.zeros_like(t)
    for cue in cues:
        relative = t - max(0, cue - .16)
        active = (relative >= 0) & (relative < .42)
        if not active.any():
            continue
        local = relative[active]
        envelope = np.sin(np.pi * local / .42) ** 2
        # Tapered sweep and low transient accent each intentional edit point.
        noise = rng.standard_normal(len(local))
        smooth = np.convolve(noise, np.ones(9)/9, mode='same')
        sweep = np.sin(2*np.pi*(480*local + 1700*local**2))
        audio[active] += envelope * (.025*smooth + .008*sweep)
        impact_time = t - cue
        impact = (impact_time >= 0) & (impact_time < .28)
        u = impact_time[impact]
        audio[impact] += .035*np.sin(2*np.pi*(78*u-40*u*u))*np.exp(-22*u)*np.clip(u/.008,0,1)
    audio *= np.clip((duration-t)/.4,0,1)
    pcm = np.rint(np.clip(audio, -.25, .25) * 32767).astype('<i2')
    with wave.open(str(target), 'wb') as wav:
        wav.setparams((1, 2, rate, 0, 'NONE', 'none'))
        wav.writeframes(pcm.tobytes())
