"""Strip markdown formatting for cleaner TTS output.

Usable as an importable module or as a stdin-to-stdout script.
The regex pipeline preserves inline code content (strips only backticks),
removes fenced code blocks, tables, and markdown formatting, then
truncates to 1000 characters.
"""
import re


def strip_markdown(text: str) -> str:
    """Strip markdown formatting from text for TTS."""
    text = re.sub(r'```[\s\S]*?```', '', text)
    text = re.sub(r'`([^`]+)`', r'\1', text)
    text = re.sub(r'\[([^\]]+)\]\([^)]+\)', r'\1', text)
    text = re.sub(r'^#{1,6}\s+', '', text, flags=re.M)
    text = re.sub(r'^\s*[-*]\s+', '', text, flags=re.M)
    text = re.sub(r'^\s*\d+\.\s+', '', text, flags=re.M)
    text = re.sub(r'^\|.*\|$', '', text, flags=re.M)
    text = re.sub(r'^[-|:\s]+$', '', text, flags=re.M)
    text = re.sub(r'\*{1,2}([^*]+)\*{1,2}', r'\1', text)
    text = re.sub(r'\n{2,}', '. ', text)
    text = re.sub(r'\s+', ' ', text).strip()
    return text[:1000]


if __name__ == "__main__":
    import sys
    print(strip_markdown(sys.stdin.read()))
