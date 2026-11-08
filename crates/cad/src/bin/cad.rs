//! `cad` — command-line client.
//!
//! Forwards argv to the per-user `cadd` daemon over a Unix socket, starting the
//! daemon automatically if needed.  `cad run`, `--no-daemon` and
//! `CAD_NO_DAEMON=1` execute the Python CLI directly instead (standalone mode,
//! identical semantics, no persistent state beyond the project's .cad directory).
//!
//! Daemon management: `cad daemon status|stop|start|restart`.

use cadcore::*;
use serde_json::{json, Value};
use std::env;
use std::io::{BufRead, BufReader, Write};
use std::os::unix::net::UnixStream;
use std::os::unix::process::CommandExt;
use std::path::PathBuf;
use std::process::{Command, Stdio};
use std::time::{Duration, Instant};

fn main() {
    let mut args: Vec<String> = env::args().skip(1).collect();
    let mut no_daemon = env::var("CAD_NO_DAEMON").map(|v| v == "1").unwrap_or(false);
    let mut timeout_s: u64 = env::var("CAD_TIMEOUT").ok().and_then(|v| v.parse().ok()).unwrap_or(600);
    let mut i = 0;
    while i < args.len() {
        match args[i].as_str() {
            "--no-daemon" => {
                no_daemon = true;
                args.remove(i);
            }
            "--timeout" if i + 1 < args.len() => {
                timeout_s = args[i + 1].parse().unwrap_or(timeout_s);
                args.drain(i..i + 2);
            }
            _ => i += 1,
        }
    }
    let json_out = args.iter().any(|a| a == "--json");
    let first = args.iter().find(|a| !a.starts_with('-')).cloned().unwrap_or_default();

    if first == "daemon" {
        std::process::exit(daemon_cmd(&args, json_out));
    }
    if no_daemon || first == "run" {
        exec_standalone(&args);
    }
    let cwd = env::current_dir().unwrap_or_else(|_| PathBuf::from("/"));
    let req = json!({"argv": args, "cwd": cwd, "timeout_s": timeout_s});
    match request(&req, true, Duration::from_secs(timeout_s + 30)) {
        Ok(resp) => {
            let out = resp["stdout"].as_str().unwrap_or("");
            let err = resp["stderr"].as_str().unwrap_or("");
            print!("{out}");
            eprint!("{err}");
            let _ = std::io::stdout().flush();
            std::process::exit(resp["exit_code"].as_i64().unwrap_or(1) as i32);
        }
        Err(e) => {
            if json_out {
                println!("{}", error_json(&first, "DAEMON_UNAVAILABLE", &e, "retry with --no-daemon, or see `cad daemon status`", exit::DAEMON_UNAVAILABLE));
            } else {
                eprintln!("error [DAEMON_UNAVAILABLE]: {e}\n  hint: retry with --no-daemon, or see `cad daemon status`");
            }
            std::process::exit(exit::DAEMON_UNAVAILABLE);
        }
    }
}

fn exec_standalone(args: &[String]) -> ! {
    let py = python();
    let err = Command::new(&py).arg("-m").arg("cad").args(args).exec();
    eprintln!("error: could not execute {}: {err}\n  hint: set CAD_PYTHON to a Python with the cad package installed", py.display());
    std::process::exit(exit::INTERNAL);
}

fn connect() -> std::io::Result<UnixStream> {
    UnixStream::connect(socket_path())
}

fn request(req: &Value, autostart: bool, timeout: Duration) -> Result<Value, String> {
    let mut stream = match connect() {
        Ok(s) => s,
        Err(_) if autostart => {
            start_daemon()?;
            connect().map_err(|e| format!("daemon started but socket is not accepting connections: {e}"))?
        }
        Err(e) => return Err(format!("daemon is not running ({e})")),
    };
    stream.set_read_timeout(Some(timeout)).ok();
    let mut line = req.to_string();
    line.push('\n');
    stream.write_all(line.as_bytes()).map_err(|e| format!("send failed: {e}"))?;
    let mut reader = BufReader::new(stream);
    let mut resp = String::new();
    reader.read_line(&mut resp).map_err(|e| format!("no response from daemon: {e}"))?;
    if resp.is_empty() {
        return Err("daemon closed the connection without responding".into());
    }
    serde_json::from_str(&resp).map_err(|e| format!("bad response from daemon: {e}"))
}

fn daemon_binary() -> PathBuf {
    let exe = env::current_exe().unwrap_or_else(|_| PathBuf::from("cad"));
    let sib = exe.with_file_name("cadd");
    if sib.exists() { sib } else { PathBuf::from("cadd") }
}

fn start_daemon() -> Result<(), String> {
    let logdir = state_dir().join("logs");
    std::fs::create_dir_all(&logdir).map_err(|e| e.to_string())?;
    let log = std::fs::OpenOptions::new().create(true).append(true).open(logdir.join("cadd.log")).map_err(|e| e.to_string())?;
    let log2 = log.try_clone().map_err(|e| e.to_string())?;
    let mut cmd = Command::new(daemon_binary());
    cmd.stdin(Stdio::null()).stdout(log).stderr(log2);
    unsafe {
        cmd.pre_exec(|| {
            libc::setsid();
            Ok(())
        });
    }
    let mut child = cmd.spawn().map_err(|e| format!("could not start daemon {}: {e}", daemon_binary().display()))?;
    let t0 = Instant::now();
    while t0.elapsed() < Duration::from_secs(15) {
        if connect().is_ok() {
            return Ok(());
        }
        if let Ok(Some(status)) = child.try_wait() {
            if connect().is_ok() {
                return Ok(()); // another daemon won the race
            }
            let log = std::fs::read_to_string(logdir.join("cadd.log")).unwrap_or_default();
            let tail: String = log.lines().rev().take(3).collect::<Vec<_>>().into_iter().rev().collect::<Vec<_>>().join("\n");
            return Err(format!("daemon exited during startup ({status}): {tail}"));
        }
        std::thread::sleep(Duration::from_millis(25));
    }
    Err("timed out waiting for the daemon to start (see ~/.local/state/cad/logs/cadd.log)".into())
}

fn daemon_cmd(args: &[String], json_out: bool) -> i32 {
    let sub = args.iter().filter(|a| !a.starts_with('-')).nth(1).map(|s| s.as_str()).unwrap_or("status");
    let print = |v: &Value, text: String| {
        if json_out {
            println!("{}", serde_json::to_string_pretty(&json!({"ok": true, "command": "daemon", "result": v})).unwrap());
        } else {
            println!("{text}");
        }
    };
    match sub {
        "start" => match connect() {
            Ok(_) => {
                print(&json!({"running": true, "started": false}), "daemon already running".into());
                0
            }
            Err(_) => match start_daemon() {
                Ok(()) => {
                    print(&json!({"running": true, "started": true}), format!("daemon started ({})", socket_path().display()));
                    0
                }
                Err(e) => {
                    eprintln!("error [DAEMON_UNAVAILABLE]: {e}");
                    exit::DAEMON_UNAVAILABLE
                }
            },
        },
        "stop" | "restart" => {
            let was = request(&json!({"argv": ["daemon", "stop"]}), false, Duration::from_secs(10)).is_ok();
            let t0 = Instant::now();
            while connect().is_ok() && t0.elapsed() < Duration::from_secs(5) {
                std::thread::sleep(Duration::from_millis(20));
            }
            if sub == "restart" {
                return daemon_cmd(&["daemon".into(), "start".into()], json_out);
            }
            print(&json!({"stopped": was}), if was { "daemon stopped".into() } else { "daemon was not running".into() });
            0
        }
        "status" => match request(&json!({"argv": ["daemon", "status"]}), false, Duration::from_secs(10)) {
            Ok(resp) => {
                let st = &resp["result"];
                let mut text = format!(
                    "daemon pid {} up {}s, socket {}\n",
                    st["pid"], st["uptime_s"], socket_path().display()
                );
                if let Some(ws) = st["workers"].as_array() {
                    for w in ws {
                        text += &format!("  worker {} pid {} requests {} restarts {} rss {}KB\n", w["session"], w["pid"], w["requests"], w["restarts"], w["max_rss_kb"]);
                    }
                }
                print(st, text.trim_end().into());
                0
            }
            Err(_) => {
                print(&json!({"running": false}), "daemon not running".into());
                0
            }
        },
        other => {
            eprintln!("error [USAGE]: unknown daemon command {other:?} (use start|stop|restart|status)");
            exit::USAGE
        }
    }
}
