"""Long-running model worker (one per project session), driven by the daemon.

Protocol: newline-delimited JSON on stdin/stdout.

  -> {"id": 1, "argv": ["build", "--json"], "cwd": "/path"}
  <- {"id": 1, "exit_code": 0, "stdout": "...", "stderr": "...", "duration_ms": 12.3}

  -> {"id": 2, "op": "ping"}          <- {"id": 2, "ok": true, "pid": 123, ...}
  -> {"id": 3, "op": "shutdown"}      (worker exits)

On start the worker prints {"ready": true, "pid": ..., "version": ...}.

The protocol uses a private duplicate of the original stdout; file descriptor 1
is redirected to stderr so that anything the geometry kernel prints directly
cannot corrupt the protocol stream.
"""

from __future__ import annotations

import json
import os
import sys
import time


def main() -> None:
    proto_fd = os.dup(1)
    os.dup2(2, 1)  # stray native/Python prints go to the daemon log, not the protocol
    proto = os.fdopen(proto_fd, "w", buffering=1)
    sys.stdout = sys.stderr

    t0 = time.perf_counter()
    from . import __version__
    from .cli import main as cli_main
    from .engine import Engine

    import cad.part  # noqa: F401  (warm the OCCT imports before reporting ready)
    import cad.renderer  # noqa: F401

    engine = Engine()
    served = 0
    proto.write(json.dumps({"ready": True, "pid": os.getpid(), "version": __version__,
                            "startup_ms": round((time.perf_counter() - t0) * 1000, 1)}) + "\n")
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except json.JSONDecodeError as e:
            proto.write(json.dumps({"id": None, "exit_code": 2, "stdout": "", "stderr": f"bad request: {e}\n"}) + "\n")
            continue
        rid = req.get("id")
        op = req.get("op")
        if op == "shutdown":
            break
        if op == "ping":
            import resource

            ru = resource.getrusage(resource.RUSAGE_SELF)
            proto.write(json.dumps({"id": rid, "ok": True, "pid": os.getpid(), "served": served,
                                    "max_rss_kb": ru.ru_maxrss // (1024 if sys.platform == "darwin" else 1),
                                    "sessions": {str(k): dict(v.stats) for k, v in engine.sessions.items()}}) + "\n")
            continue
        t = time.perf_counter()
        code, out, err = cli_main(list(req.get("argv", [])), req.get("cwd") or os.getcwd(), engine)
        served += 1
        proto.write(json.dumps({"id": rid, "exit_code": code, "stdout": out, "stderr": err,
                                "duration_ms": round((time.perf_counter() - t) * 1000, 2)}) + "\n")
    proto.flush()


if __name__ == "__main__":
    main()
