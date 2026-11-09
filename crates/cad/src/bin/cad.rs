//! `cad` — command-line client.
//!
//! Forwards argv to the per-user `cadd` daemon over a Unix socket, starting the
//! daemon automatically if needed.  `cad run`, `--no-daemon` and
//! `CAD_NO_DAEMON=1` execute the Python CLI directly instead (standalone mode,
//! identical semantics, no persistent state beyond the project's .cad directory).
//!
//! If the daemon cannot be reached or started (e.g. a sandbox such as Codex's forbids
//! Unix sockets), the client falls back to standalone mode automatically and says so
//! on stderr; set `CAD_REQUIRE_DAEMON=1` to make that an error instead.
//!
//! Each installation has its own daemon (socket named by `install_id`), and a daemon older than
//! this install's `cadd` is replaced on the next command. Daemon management: `cad daemon status|stop|start|restart`.

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
    let mut timeout_s: u64 = env::var("CAD_TIMEOUT")
        .ok()
        .and_then(|v| v.parse().ok())
        .unwrap_or(600);
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
    let first = args
        .iter()
        .find(|a| !a.starts_with('-'))
        .cloned()
        .unwrap_or_default();

    if first == "daemon" {
        std::process::exit(daemon_cmd(&args, json_out));
    }
    if no_daemon || first == "run" {
        exec_standalone(&args);
    }
    let cwd = env::current_dir().unwrap_or_else(|_| PathBuf::from("/"));
    let build = build_id(&daemon_binary());
    let req = json!({"argv": args, "cwd": cwd, "timeout_s": timeout_s, "build": build});
    let require = env::var("CAD_REQUIRE_DAEMON")
        .map(|v| v == "1")
        .unwrap_or(false);
    let mut replaced_old = false;
    let resp = loop {
        let stream = match connect_or_start() {
            Ok(s) => s,
            Err(reason) if !require => {
                // same engine in-process: identical results, just no warm session
                eprintln!("note: cad daemon unavailable ({reason}); running standalone. Set CAD_NO_DAEMON=1 to skip this check.");
                exec_standalone(&args);
            }
            Err(reason) => {
                if json_out {
                    println!(
                        "{}",
                        error_json(
                            &first,
                            "DAEMON_UNAVAILABLE",
                            &reason,
                            "unset CAD_REQUIRE_DAEMON or retry with --no-daemon",
                            exit::DAEMON_UNAVAILABLE
                        )
                    );
                } else {
                    eprintln!("error [DAEMON_UNAVAILABLE]: {reason}\n  hint: unset CAD_REQUIRE_DAEMON or retry with --no-daemon");
                }
                std::process::exit(exit::DAEMON_UNAVAILABLE);
            }
        };
        let resp = send(stream, &req, Duration::from_secs(timeout_s + 30));
        // the running daemon predates this install's cadd (rebuilt or reinstalled): it has stepped
        // aside, so start the new one and send the request again
        if !replaced_old && matches!(&resp, Ok(r) if r["restart"] == true) {
            replaced_old = true;
            continue;
        }
        break resp;
    };
    match resp {
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
                println!(
                    "{}",
                    error_json(
                        &first,
                        "DAEMON_UNAVAILABLE",
                        &e,
                        "retry with --no-daemon, or see `cad daemon status`",
                        exit::DAEMON_UNAVAILABLE
                    )
                );
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
    UnixStream::connect(socket_path(&daemon_binary()))
}

/// Connect to the daemon, starting it if needed.  A socket refused with EPERM/EACCES
/// means a sandbox forbids Unix sockets: don't try to start a daemon that cannot bind.
fn connect_or_start() -> Result<UnixStream, String> {
    match connect() {
        Ok(s) => Ok(s),
        Err(e)
            if e.kind() == std::io::ErrorKind::PermissionDenied
                || e.raw_os_error() == Some(libc::EPERM) =>
        {
            Err(format!("Unix sockets are not permitted here: {e}"))
        }
        Err(_) => {
            start_daemon().map_err(|e| format!("could not start the daemon: {e}"))?;
            connect().map_err(|e| {
                format!("daemon started but its socket is not accepting connections: {e}")
            })
        }
    }
}

fn request(req: &Value, autostart: bool, timeout: Duration) -> Result<Value, String> {
    let stream = match connect() {
        Ok(s) => s,
        Err(_) if autostart => connect_or_start()?,
        Err(e) => return Err(format!("daemon is not running ({e})")),
    };
    send(stream, req, timeout)
}

fn send(mut stream: UnixStream, req: &Value, timeout: Duration) -> Result<Value, String> {
    stream.set_read_timeout(Some(timeout)).ok();
    let mut line = req.to_string();
    line.push('\n');
    stream
        .write_all(line.as_bytes())
        .map_err(|e| format!("send failed: {e}"))?;
    let mut reader = BufReader::new(stream);
    let mut resp = String::new();
    reader
        .read_line(&mut resp)
        .map_err(|e| format!("no response from daemon: {e}"))?;
    if resp.is_empty() {
        return Err("daemon closed the connection without responding".into());
    }
    serde_json::from_str(&resp).map_err(|e| format!("bad response from daemon: {e}"))
}

fn start_daemon() -> Result<(), String> {
    let logdir = state_dir().join("logs");
    std::fs::create_dir_all(&logdir).map_err(|e| e.to_string())?;
    let log_path = logdir.join("cadd.log");
    let log_start = std::fs::metadata(&log_path).map(|m| m.len()).unwrap_or(0);
    let log = std::fs::OpenOptions::new()
        .create(true)
        .append(true)
        .open(&log_path)
        .map_err(|e| e.to_string())?;
    let log2 = log.try_clone().map_err(|e| e.to_string())?;
    let mut cmd = Command::new(daemon_binary());
    cmd.stdin(Stdio::null()).stdout(log).stderr(log2);
    unsafe {
        cmd.pre_exec(|| {
            libc::setsid();
            Ok(())
        });
    }
    let mut child = cmd
        .spawn()
        .map_err(|e| format!("could not start daemon {}: {e}", daemon_binary().display()))?;
    let t0 = Instant::now();
    while t0.elapsed() < Duration::from_secs(15) {
        if connect().is_ok() {
            return Ok(());
        }
        if let Ok(Some(status)) = child.try_wait() {
            if connect().is_ok() {
                return Ok(()); // another daemon won the race
            }
            // only what this startup wrote, not older runs' lines
            let log = std::fs::read(&log_path).unwrap_or_default();
            let fresh =
                String::from_utf8_lossy(&log[(log_start as usize).min(log.len())..]).into_owned();
            let tail = fresh.lines().last().unwrap_or("").to_string();
            return Err(format!(
                "daemon exited during startup ({status}){}",
                if tail.is_empty() {
                    String::new()
                } else {
                    format!(": {tail}")
                }
            ));
        }
        std::thread::sleep(Duration::from_millis(25));
    }
    Err("timed out waiting for the daemon to start (see ~/.local/state/cad/logs/cadd.log)".into())
}

fn daemon_cmd(args: &[String], json_out: bool) -> i32 {
    let sub = args
        .iter()
        .filter(|a| !a.starts_with('-'))
        .nth(1)
        .map(|s| s.as_str())
        .unwrap_or("status");
    let print = |v: &Value, text: String| {
        if json_out {
            println!(
                "{}",
                serde_json::to_string_pretty(
                    &json!({"ok": true, "command": "daemon", "result": v})
                )
                .unwrap()
            );
        } else {
            println!("{text}");
        }
    };
    match sub {
        "start" => match connect() {
            Ok(_) => {
                print(
                    &json!({"running": true, "started": false}),
                    "daemon already running".into(),
                );
                0
            }
            Err(_) => match start_daemon() {
                Ok(()) => {
                    print(
                        &json!({"running": true, "started": true}),
                        format!(
                            "daemon started ({})",
                            socket_path(&daemon_binary()).display()
                        ),
                    );
                    0
                }
                Err(e) => {
                    eprintln!("error [DAEMON_UNAVAILABLE]: {e}");
                    exit::DAEMON_UNAVAILABLE
                }
            },
        },
        "stop" | "restart" => {
            let was = request(
                &json!({"argv": ["daemon", "stop"]}),
                false,
                Duration::from_secs(10),
            )
            .is_ok();
            let t0 = Instant::now();
            while connect().is_ok() && t0.elapsed() < Duration::from_secs(5) {
                std::thread::sleep(Duration::from_millis(20));
            }
            if sub == "restart" {
                return daemon_cmd(&["daemon".into(), "start".into()], json_out);
            }
            print(
                &json!({"stopped": was}),
                if was {
                    "daemon stopped".into()
                } else {
                    "daemon was not running".into()
                },
            );
            0
        }
        "status" => match request(
            &json!({"argv": ["daemon", "status"]}),
            false,
            Duration::from_secs(10),
        ) {
            Ok(resp) => {
                let st = &resp["result"];
                let mut text = format!(
                    "daemon pid {} up {}s, socket {}\n  cadd {}, python {}\n",
                    st["pid"],
                    st["uptime_s"],
                    socket_path(&daemon_binary()).display(),
                    st["cadd"].as_str().unwrap_or("?"),
                    st["python"].as_str().unwrap_or("?")
                );
                if st["build"].as_str() != Some(build_id(&daemon_binary()).as_str()) {
                    text += "  older than the installed cadd: the next command replaces it\n";
                }
                if let Some(ws) = st["workers"].as_array() {
                    for w in ws {
                        text += &format!(
                            "  worker {} pid {} requests {} restarts {} rss {}KB\n",
                            w["session"], w["pid"], w["requests"], w["restarts"], w["max_rss_kb"]
                        );
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
            eprintln!(
                "error [USAGE]: unknown daemon command {other:?} (use start|stop|restart|status)"
            );
            exit::USAGE
        }
    }
}
