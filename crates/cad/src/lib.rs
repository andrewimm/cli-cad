//! Shared pieces of the `cad` client and the `cadd` session daemon:
//! filesystem locations, project resolution, Python discovery and the wire protocol.
//!
//! Wire protocol (client <-> daemon): one JSON object per line over a Unix socket.
//!   request : {"argv": [...], "cwd": "/abs/path", "timeout_s": 600, "build": "<build_id>"}
//!   response: {"exit_code": 0, "stdout": "...", "stderr": "..."}
//!             or {"restart": true} when "build" differs from the daemon's own: the daemon was built
//!             before the client's `cadd` was replaced, so it exits and the client starts the new one.

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

fn fnv(parts: &[&[u8]]) -> u64 {
    let mut h: u64 = 0xcbf29ce484222325;
    for part in parts {
        for b in part.iter().chain(&[0u8]) {
            h = (h ^ *b as u64).wrapping_mul(0x100000001b3);
        }
    }
    h
}

/// The `cadd` binary the client starts: the one next to the running `cad`, else `cadd` on PATH.
pub fn daemon_binary() -> PathBuf {
    let exe = env::current_exe().unwrap_or_else(|_| PathBuf::from("cad"));
    let sib = exe.with_file_name("cadd");
    if sib.exists() {
        return sib;
    }
    env::var_os("PATH")
        .and_then(|paths| {
            env::split_paths(&paths)
                .map(|d| d.join("cadd"))
                .find(|p| p.is_file())
        })
        .unwrap_or_else(|| PathBuf::from("cadd"))
}

/// Which installation a daemon serves: its `cadd` binary and the Python its workers run.
/// Every installation (and every `CAD_PYTHON`) gets its own daemon and socket, so two installs
/// never answer each other's commands. The client passes the `cadd` it would start; the daemon its own exe.
pub fn install_id(cadd: &Path) -> String {
    let cadd = fs::canonicalize(cadd).unwrap_or_else(|_| cadd.to_path_buf());
    let py = python();
    format!(
        "{:012x}",
        fnv(&[
            cadd.as_os_str().as_encoded_bytes(),
            py.as_os_str().as_encoded_bytes()
        ]) & 0xffff_ffff_ffff
    )
}

/// Changes whenever the `cadd` binary is rebuilt or replaced (its size and modification time), so a
/// client can tell that the running daemon is older than the one it would start, and restart it.
pub fn build_id(cadd: &Path) -> String {
    let m = fs::metadata(cadd);
    let len = m.as_ref().map(|m| m.len()).unwrap_or(0);
    let mtime = m
        .and_then(|m| m.modified())
        .ok()
        .and_then(|t| t.duration_since(std::time::UNIX_EPOCH).ok())
        .map(|d| d.as_nanos())
        .unwrap_or(0);
    format!("{:016x}", fnv(&[&len.to_le_bytes(), &mtime.to_le_bytes()]))
}

/// Socket of the daemon for one installation (see `install_id`). Unix socket paths are limited to
/// ~104 bytes; very long runtime dirs fall back to a short per-user path derived from a hash.
pub fn socket_path(cadd: &Path) -> PathBuf {
    let p = runtime_dir().join(format!("cadd-{}.sock", install_id(cadd)));
    if p.as_os_str().len() < 100 {
        return p;
    }
    let h = fnv(&[p.as_os_str().as_encoded_bytes()]);
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
