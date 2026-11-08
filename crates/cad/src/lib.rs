//! Shared pieces of the `cad` client and the `cadd` session daemon:
//! filesystem locations, project resolution, Python discovery and the wire protocol.
//!
//! Wire protocol (client <-> daemon): one JSON object per line over a Unix socket.
//!   request : {"argv": [...], "cwd": "/abs/path", "timeout_s": 600}
//!   response: {"exit_code": 0, "stdout": "...", "stderr": "..."}

use std::env;
use std::fs;
use std::path::{Path, PathBuf};

pub mod exit {
    pub const OK: i32 = 0;
    pub const INTERNAL: i32 = 1;
    pub const USAGE: i32 = 2;
    pub const WORKER_CRASHED: i32 = 6;
    pub const TIMEOUT: i32 = 7;
    pub const DAEMON_UNAVAILABLE: i32 = 8;
}

/// Commands that never need a project; they run in the shared "global" worker.
pub const GLOBAL_COMMANDS: &[&str] = &[
    "init",
    "open",
    "run",
    "capabilities",
    "schema",
    "examples",
    "docs",
    "help",
    "--version",
    "--help",
    "-h",
];

pub const GLOBAL_KEY: &str = "<global>";

fn uid() -> u32 {
    unsafe { libc::getuid() }
}

/// Directory holding the daemon socket and pid file.
/// `$CAD_RUNTIME_DIR`, else `$XDG_RUNTIME_DIR/cad` (Linux), else `$TMPDIR/cad-<uid>`.
pub fn runtime_dir() -> PathBuf {
    if let Ok(d) = env::var("CAD_RUNTIME_DIR") {
        return PathBuf::from(d);
    }
    if let Ok(d) = env::var("XDG_RUNTIME_DIR") {
        if !d.is_empty() {
            return PathBuf::from(d).join("cad");
        }
    }
    let tmp = env::var("TMPDIR").unwrap_or_else(|_| "/tmp".into());
    PathBuf::from(tmp).join(format!("cad-{}", uid()))
}

/// Unix socket paths are limited to ~104 bytes; very long runtime dirs fall back
/// to a short per-user path derived from a hash of the requested location.
pub fn socket_path() -> PathBuf {
    let p = runtime_dir().join("cadd.sock");
    if p.as_os_str().len() < 100 {
        return p;
    }
    let mut h: u64 = 0xcbf29ce484222325;
    for b in p.as_os_str().as_encoded_bytes() {
        h = (h ^ *b as u64).wrapping_mul(0x100000001b3);
    }
    PathBuf::from(format!("/tmp/cad-{}", uid())).join(format!("{:016x}.sock", h))
}

/// Persistent per-user state (logs, current project): `$CAD_STATE_DIR` or `$XDG_STATE_HOME/cad`.
pub fn state_dir() -> PathBuf {
    if let Ok(d) = env::var("CAD_STATE_DIR") {
        return PathBuf::from(d);
    }
    let base = env::var("XDG_STATE_HOME")
        .ok()
        .filter(|s| !s.is_empty())
        .map(PathBuf::from)
        .unwrap_or_else(|| {
            PathBuf::from(env::var("HOME").unwrap_or_else(|_| "/tmp".into())).join(".local/state")
        });
    base.join("cad")
}

pub fn ensure_private_dir(p: &Path) -> std::io::Result<()> {
    fs::create_dir_all(p)?;
    use std::os::unix::fs::PermissionsExt;
    fs::set_permissions(p, fs::Permissions::from_mode(0o700))
}

/// Walk up from `start` to find a directory containing cad.toml.
pub fn find_project_root(start: &Path) -> Option<PathBuf> {
    let mut d = if start.is_file() {
        start.parent()?.to_path_buf()
    } else {
        start.to_path_buf()
    };
    loop {
        if d.join("cad.toml").is_file() {
            return Some(d);
        }
        if !d.pop() {
            return None;
        }
    }
}

/// Session key for a request: the project root, or GLOBAL_KEY for project-less commands.
/// Mirrors the Python resolution order: --project/-C, cwd ancestors, then the opened project.
pub fn session_key(argv: &[String], cwd: &Path) -> String {
    let cmd = argv
        .iter()
        .find(|a| !a.starts_with('-') || a.as_str() == "--version")
        .map(|s| s.as_str())
        .unwrap_or("");
    if cmd.is_empty() || GLOBAL_COMMANDS.contains(&cmd) {
        return GLOBAL_KEY.into();
    }
    let mut it = argv.iter();
    while let Some(a) = it.next() {
        let given = if a == "--project" || a == "-C" {
            it.next().cloned()
        } else {
            a.strip_prefix("--project=").map(|s| s.to_string())
        };
        if let Some(p) = given {
            let p = cwd.join(p);
            return find_project_root(&p)
                .map(|r| canon(&r))
                .unwrap_or_else(|| GLOBAL_KEY.into());
        }
    }
    if let Some(r) = find_project_root(cwd) {
        return canon(&r);
    }
    if let Ok(s) = fs::read_to_string(state_dir().join("current_project")) {
        let p = PathBuf::from(s.trim());
        if p.join("cad.toml").is_file() {
            return canon(&p);
        }
    }
    GLOBAL_KEY.into()
}

fn canon(p: &Path) -> String {
    fs::canonicalize(p)
        .unwrap_or_else(|_| p.to_path_buf())
        .to_string_lossy()
        .into_owned()
}

/// Python interpreter that has the `cad` package installed.
/// `$CAD_PYTHON`, else a `.venv/bin/python` next to (or above) this executable, else `python3`.
pub fn python() -> PathBuf {
    if let Ok(p) = env::var("CAD_PYTHON") {
        return PathBuf::from(p);
    }
    if let Ok(exe) = env::current_exe() {
        let exe = fs::canonicalize(&exe).unwrap_or(exe);
        let mut d = exe.parent().map(|p| p.to_path_buf());
        while let Some(dir) = d {
            let cand = dir.join(".venv/bin/python");
            if cand.exists() {
                return cand;
            }
            d = dir.parent().map(|p| p.to_path_buf());
        }
    }
    PathBuf::from("python3")
}

pub fn error_json(command: &str, code: &str, message: &str, hint: &str, exit_code: i32) -> String {
    serde_json::json!({
        "ok": false,
        "command": command,
        "error": {"code": code, "message": message, "hint": hint},
        "exit_code": exit_code,
    })
    .to_string()
}
