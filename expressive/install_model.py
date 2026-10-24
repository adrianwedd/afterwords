"""Install pinned Fish weights into the model root (default ~/models).

Run: .venv-drama3/bin/python -m expressive.install_model [--model M --revision R]
An existing HF cache snapshot is hard-linked (no extra disk); otherwise the
pinned revision is downloaded straight into place. Afterwards the HF cache may
be cleared without affecting the sidecar.
"""
import argparse
import json
import os
from pathlib import Path

from expressive.contracts import MODEL, PIN_FILE, REVISION, model_dir


def install(model, revision):
    from huggingface_hub import snapshot_download
    path = model_dir(model)
    path.mkdir(parents=True, exist_ok=True)
    try:
        cached = Path(snapshot_download(model, revision=revision, local_files_only=True))
    except Exception:
        cached = None
    if cached is not None:
        for source in cached.rglob('*'):
            target = path / source.relative_to(cached)
            if source.is_dir() or target.exists():
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            os.link(source.resolve(), target)
    else:
        snapshot_download(model, revision=revision, local_dir=path)
    (path / PIN_FILE).write_text(json.dumps({'model': model, 'revision': revision}) + '\n')
    return path


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--model', default=MODEL)
    p.add_argument('--revision', default=REVISION)
    a = p.parse_args()
    print(install(a.model, a.revision))


if __name__ == '__main__':
    main()
