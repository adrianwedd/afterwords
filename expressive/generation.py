"""Optional paragraph isolation for literal long-form narration."""
import re


def paragraph_segments(text):
    """Keep every character; attach punctuation-only separators to nearby prose."""
    parts = []
    start = 0
    for match in re.finditer(r'\n[ \t]*\n', text):
        parts.append(text[start:match.end()])
        start = match.end()
    if start < len(text):
        parts.append(text[start:])
    segments, pending = [], ''
    for part in parts:
        pending += part
        if any(char.isalnum() for char in part):
            segments.append(pending)
            pending = ''
    if pending:
        if segments:
            segments[-1] += pending
        else:
            segments.append(pending)
    return segments


def generate_with_context(model, text, reference, reference_text, options, set_seed):
    """Reset history/codec at paragraph boundaries; never retry or repair text."""
    segments = paragraph_segments(text) if options['context_mode'] == 'paragraphs' else [text]
    for index, segment in enumerate(segments):
        set_seed(options['seed'])
        produced = False
        for result in model.generate(
                text=segment, ref_audio=reference, ref_text=reference_text,
                stream=True, first_chunk_frames=4, max_tokens=options['max_frames'],
                temperature=options['temperature'], top_p=options['top_p'],
                top_k=options['top_k']):
            produced = produced or len(result.audio) > 0
            yield result
        if not produced:
            raise RuntimeError(f'text segment {index} generated no audio')
