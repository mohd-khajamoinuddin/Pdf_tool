"""Entry point: ``python -m docsuite_engine`` (or the frozen PyInstaller binary)."""

from __future__ import annotations

import io
import sys


def main() -> None:
    # Reserve the real stdout for the protocol. Anything a third-party library
    # prints goes to stderr, where the shell logs it instead of parsing it.
    proto_out = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", newline="\n", write_through=True)
    proto_in = io.TextIOWrapper(sys.stdin.buffer, encoding="utf-8", newline="\n")
    sys.stdout = sys.stderr

    from . import handlers  # noqa: F401 - importing registers every RPC method
    from .rpc import serve

    serve(proto_in, proto_out)


if __name__ == "__main__":
    main()
