"""CLI used by clone-voice.sh to query registry state from Bash."""
from __future__ import annotations

import sys

from . import max_sample_rate, names, register_all, slug


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print("usage: python -m backends <list|max-sample-rate|slug NAME>", file=sys.stderr)
        return 2

    register_all()
    cmd = argv[1]

    if cmd == "list":
        for n in names():
            print(n)
        return 0
    if cmd == "max-sample-rate":
        print(max_sample_rate())
        return 0
    if cmd == "slug":
        if len(argv) < 3:
            print("usage: python -m backends slug NAME", file=sys.stderr)
            return 2
        print(slug(argv[2]))
        return 0

    print(f"unknown command: {cmd}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
