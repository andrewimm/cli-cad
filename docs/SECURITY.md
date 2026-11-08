# Security model

**Model scripts are arbitrary Python code.** `cad build`, `cad run`, the model
worker and the eval grader execute them with the full privileges of the user
running `cad`. Process isolation in this system exists for *robustness*
(a kernel crash or runaway computation does not take down the daemon or other
projects); it is **not** a security boundary.

Current guarantees:

- The daemon socket lives in a per-user directory created with mode `0700`
  (`$XDG_RUNTIME_DIR/cad`, or `$TMPDIR/cad-<uid>`; very long paths fall back to
  `/tmp/cad-<uid>/`), so other local users cannot send commands.
- Each project runs in its own worker process; optional `CAD_WORKER_MAX_MEM_MB`
  (RLIMIT_AS, effective on Linux) and `CAD_WORKER_CPU_SECS` (RLIMIT_CPU) bound
  resource use, and per-request timeouts kill stuck workers.
- `cad query` evaluates its expression with Python `eval` (builtins removed) in
  the worker. This is a convenience for trusted local use, not a sandbox.

Before accepting scripts or query expressions from untrusted sources you need
OS-level sandboxing around the worker, for example:

- Linux: run workers in a container or under `bubblewrap`/`nsjail` with no
  network, a read-only filesystem except the project and cache directories,
  seccomp, and cgroup CPU/memory limits.
- macOS: `sandbox-exec` profiles or a VM.

The daemon's worker spawn point (`spawn_worker` in `crates/cad/src/bin/cadd.rs`)
is the single place to add such a wrapper.
