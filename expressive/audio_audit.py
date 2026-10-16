"""Deterministic waveform and transcript measurements, not a listening verdict."""
import re
import numpy as np


def validate_delivery(audio, rate):
    """Reject observed catastrophic silence; this is not transcript verification.

    Ten seconds permits ordinary dramatic pauses while rejecting the measured
    19s and 68s silent failures. Never trim silence and present damaged text as
    complete speech. The caller must discard the full output on rejection.
    """
    measurement = waveform(audio, rate)
    if measurement['longest_silence_seconds'] >= 10:
        raise RuntimeError('generated audio contains at least ten seconds of sustained silence')
    return measurement


def words(text):
    return re.findall(r"[\w]+(?:['’][\w]+)*", text.casefold().replace('’',"'"),flags=re.UNICODE)


def word_errors(reference, hypothesis):
    expected,heard=words(reference),words(hypothesis)
    # Each cell stores edit distance and predecessor operation. Tie priority:
    # substitution, deletion, insertion; counts remain reproducible.
    dp=[[0]*(len(heard)+1) for _ in range(len(expected)+1)]
    for i in range(len(expected)+1):dp[i][0]=i
    for j in range(len(heard)+1):dp[0][j]=j
    for i,e in enumerate(expected,1):
        for j,h in enumerate(heard,1):
            dp[i][j]=min(dp[i-1][j-1]+(e!=h),dp[i-1][j]+1,dp[i][j-1]+1)
    edits=[];i,j=len(expected),len(heard)
    while i or j:
        if i and j and expected[i-1]==heard[j-1] and dp[i][j]==dp[i-1][j-1]:i-=1;j-=1
        elif i and j and dp[i][j]==dp[i-1][j-1]+1:
            edits.append({'operation':'substitution','expected':expected[i-1],'heard':heard[j-1],'expected_index':i-1});i-=1;j-=1
        elif i and dp[i][j]==dp[i-1][j]+1:
            edits.append({'operation':'deletion','expected':expected[i-1],'expected_index':i-1});i-=1
        else:
            edits.append({'operation':'insertion','heard':heard[j-1],'after_expected_index':i-1});j-=1
    edits.reverse()
    return {'reference_words':len(expected),'hypothesis_words':len(heard),
            'edit_distance':dp[-1][-1],'wer':dp[-1][-1]/len(expected) if expected else None,
            'edits':edits,'normalization':'Unicode casefold; punctuation removed; contractions retained'}


def waveform(audio, rate):
    a=np.asarray(audio)
    if a.ndim!=1 or not len(a) or rate<=0 or not np.isfinite(a).all():
        raise ValueError('audio must be nonempty finite mono samples with a positive sample rate')
    frame=max(1,round(rate*.02))
    rms=np.array([np.sqrt(np.mean(a[i:i+frame].astype(np.float64)**2)) for i in range(0,len(a),frame)])
    quiet=rms<10**(-50/20)
    runs=[];start=None
    for i,q in enumerate([*quiet,False]):
        if q and start is None:start=i
        if not q and start is not None:
            runs.append({'start_seconds':start*frame/rate,'end_seconds':min(i*frame,len(a))/rate})
            start=None
    duration=len(a)/rate
    leading=runs[0]['end_seconds'] if runs and runs[0]['start_seconds']==0 else 0
    trailing=duration-runs[-1]['start_seconds'] if runs and runs[-1]['end_seconds']==duration else 0
    return {'samples':len(a),'sample_rate':rate,'duration_seconds':duration,
            'peak_amplitude':float(np.max(np.abs(a))),
            'clipped_sample_fraction':float(np.mean(np.abs(a)>=.999)),
            'rms_amplitude':float(np.sqrt(np.mean(a.astype(np.float64)**2))),
            'silence_threshold_dbfs':-50,'analysis_frame_ms':20,
            'leading_silence_seconds':leading,'trailing_silence_seconds':trailing,
            'silence_intervals_over_200ms':[r for r in runs if r['end_seconds']-r['start_seconds']>=.2],
            'longest_silence_seconds':max((r['end_seconds']-r['start_seconds'] for r in runs),default=0)}
