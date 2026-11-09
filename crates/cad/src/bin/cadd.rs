//! `cadd` — per-user CAD session daemon.
//!
//! Listens on a Unix socket and routes each CLI request to a long-running
//! Python model worker owned by the request's project (one worker per project
//! root, plus one "global" worker for project-less commands).  Workers keep
//! loaded BRep shapes, meshes and caches in memory between commands.
//!
//! Isolation and recovery:
//! * requests to the same project are serialised; different projects run in parallel
//! * a worker that crashes is reported as WORKER_CRASHED (exit 6) and restarted
//!   on the next request; the last successful revision is recovered from disk
//! * a request exceeding its timeout kills its worker (exit 7)
//! * optional limits: CAD_WORKER_MAX_MEM_MB (RLIMIT_AS), CAD_WORKER_CPU_SECS (RLIMIT_CPU)
//! * the daemon exits after CAD_DAEMON_IDLE_SECS (default 1800) without requests
//! * one daemon per installation (socket named by `install_id`); a request from a client whose
//!   `cadd` was rebuilt since this daemon started (`build_id` differs) makes it exit for the new one

use cadcore::*;
use serde_json::{json, Value};
use std::collections::HashMap;
use std::env;
use std::fs;
use std::io::{BufRead, BufReader, Read, Seek, SeekFrom, Write};
use std::os::unix::net::{UnixListener, UnixStream};
use std::os::unix::process::CommandExt;
use std::path::PathBuf;
use std::process::{Child, ChildStdin, Command, Stdio};
use std::sync::atomic::{AtomicBool, AtomicU64, Ordering};
use std::sync::mpsc::{channel, Receiver, RecvTimeoutError};
use std::sync::{Arc, Mutex};
use std::time::{Duration, Instant, SystemTime, UNIX_EPOCH};

struct Worker {
    child: Child,
    stdin: ChildStdin,
    lines: Receiver<String>,
    pid: u32,
    started: Instant,
    requests: u64,
    log: PathBuf,
    next_id: u64,
}

#[derive(Default)]
struct Slot {
    worker: Option<Worker>,
    spawned: u64,
    crashes: u64,
}

struct Daemon {
    slots: Mutex<HashMap<String, Arc<Mutex<Slot>>>>,
    started: Instant,
    last_activity: AtomicU64,
    shutdown: AtomicBool,
    inflight: AtomicU64,
    exe: PathBuf,
    build: String,
    sock: PathBuf,
}

fn now_s() -> u64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|d| d.as_secs())
        .unwrap_or(0)
}

fn log(msg: &str) {
    eprintln!("[cadd {}] {msg}", now_s());
}

fn main() {
    let rt = runtime_dir();
    if let Err(e) = ensure_private_dir(&rt) {
        log(&format!("cannot create runtime dir {}: {e}", rt.display()));
        std::process::exit(1);
    }
    let exe = env::current_exe().unwrap_or_else(|_| PathBuf::from("cadd"));
    let exe = fs::canonicalize(&exe).unwrap_or(exe);
    let sock = socket_path(&exe);
    if let Some(parent) = sock.parent() {
        let _ = ensure_private_dir(parent);
    }
    if UnixStream::connect(&sock).is_ok() {
        log("another daemon is already running; exiting");
        return;
    }
    let _ = fs::remove_file(&sock);
    let listener = match UnixListener::bind(&sock) {
        Ok(l) => l,
        Err(e) => {
            log(&format!("cannot bind {}: {e}", sock.display()));
            std::process::exit(1);
        }
    };
    let _ = fs::write(sock.with_extension("pid"), std::process::id().to_string());
    log(&format!(
        "listening on {} ({}, python {})",
        sock.display(),
        exe.display(),
        python().display()
    ));

    let d = Arc::new(Daemon {
        slots: Mutex::new(HashMap::new()),
        started: Instant::now(),
        last_activity: AtomicU64::new(now_s()),
        shutdown: AtomicBool::new(false),
        inflight: AtomicU64::new(0),
        build: build_id(&exe),
        exe,
        sock: sock.clone(),
    });

    let idle: u64 = env::var("CAD_DAEMON_IDLE_SECS")
        .ok()
        .and_then(|v| v.parse().ok())
        .unwrap_or(1800);
    {
        let d = d.clone();
        let sock = sock.clone();
        std::thread::spawn(move || loop {
            std::thread::sleep(Duration::from_secs(5));
            if d.shutdown.load(Ordering::SeqCst) && d.inflight.load(Ordering::SeqCst) == 0 {
                exit_now(&d); // asked to stop; the socket is already gone
            }
            if now_s().saturating_sub(d.last_activity.load(Ordering::SeqCst)) > idle {
                log("idle; shutting down");
                let _ = fs::remove_file(&sock);
                exit_now(&d);
            }
        });
    }

    for conn in listener.incoming() {
        match conn {
            Ok(stream) => {
                let d = d.clone();
                std::thread::spawn(move || {
                    if let Err(e) = handle(&d, stream) {
                        log(&format!("connection error: {e}"));
                    }
                });
            }
            Err(e) => log(&format!("accept failed: {e}")),
        }
    }
}

fn exit_now(d: &Daemon) -> ! {
    shutdown_workers(d);
    let _ = fs::remove_file(d.sock.with_extension("pid"));
    std::process::exit(0);
}

/// Stop taking connections at once: the socket goes before the reply, so the client can start a
/// replacement right away, and this daemon never deletes a socket a replacement has bound.
/// Requests already running finish; the daemon exits after the last one.
fn begin_stop(d: &Daemon, why: &str) {
    log(why);
    let _ = fs::remove_file(&d.sock);
    d.shutdown.store(true, Ordering::SeqCst);
}

fn shutdown_workers(d: &Daemon) {
    let slots: Vec<_> = d.slots.lock().unwrap().values().cloned().collect();
    for s in slots {
        if let Ok(mut slot) = s.try_lock() {
            if let Some(mut w) = slot.worker.take() {
                let _ = w.stdin.write_all(b"{\"op\":\"shutdown\"}\n");
                std::thread::sleep(Duration::from_millis(50));
                let _ = w.child.kill();
                let _ = w.child.wait();
            }
        }
    }
}

fn handle(d: &Arc<Daemon>, stream: UnixStream) -> std::io::Result<()> {
    d.inflight.fetch_add(1, Ordering::SeqCst);
    let r = serve(d, stream);
    if d.inflight.fetch_sub(1, Ordering::SeqCst) == 1 && d.shutdown.load(Ordering::SeqCst) {
        exit_now(d);
    }
    r
}

fn serve(d: &Arc<Daemon>, stream: UnixStream) -> std::io::Result<()> {
    let mut reader = BufReader::new(stream.try_clone()?);
    let mut line = String::new();
    reader.read_line(&mut line)?;
    d.last_activity.store(now_s(), Ordering::SeqCst);
    let resp = match serde_json::from_str::<Value>(&line) {
        Ok(req) => dispatch(d, &req),
        Err(e) => {
            json!({"exit_code": exit::USAGE, "stdout": "", "stderr": format!("bad request: {e}\n")})
        }
    };
    d.last_activity.store(now_s(), Ordering::SeqCst);
    let mut out = resp.to_string();
    out.push('\n');
    let mut s = stream;
    s.write_all(out.as_bytes())
}

fn dispatch(d: &Arc<Daemon>, req: &Value) -> Value {
    let argv: Vec<String> = req["argv"]
        .as_array()
        .map(|a| {
            a.iter()
                .filter_map(|x| x.as_str().map(String::from))
                .collect()
        })
        .unwrap_or_default();
    if argv.first().map(|s| s.as_str()) == Some("daemon") {
        return match argv.get(1).map(|s| s.as_str()) {
            Some("stop") => {
                begin_stop(d, "stop requested; shutting down");
                json!({"exit_code": 0, "stdout": "", "stderr": ""})
            }
            _ => json!({"exit_code": 0, "result": status(d)}),
        };
    }
    if let Some(b) = req["build"].as_str() {
        if b != d.build {
            begin_stop(
                d,
                "a client with a newer cadd build connected; exiting for it",
            );
            return json!({"restart": true});
        }
    }
    let cwd = PathBuf::from(req["cwd"].as_str().unwrap_or("/"));
    let timeout = Duration::from_secs(req["timeout_s"].as_u64().unwrap_or(600));
    let key = session_key(&argv, &cwd);
    let slot = {
        let mut slots = d.slots.lock().unwrap();
        slots.entry(key.clone()).or_default().clone()
    };
    let mut slot = slot.lock().unwrap();
    forward(&mut slot, &key, &argv, &cwd, timeout)
}

fn command_name(argv: &[String]) -> String {
    argv.iter()
        .find(|a| !a.starts_with('-'))
        .cloned()
        .unwrap_or_default()
}

fn failure(argv: &[String], code: &str, msg: &str, hint: &str, exit_code: i32) -> Value {
    let json_out = argv.iter().any(|a| a == "--json");
    if json_out {
        json!({"exit_code": exit_code, "stdout": error_json(&command_name(argv), code, msg, hint) + "\n", "stderr": ""})
    } else {
        json!({"exit_code": exit_code, "stdout": "", "stderr": format!("error [{code}]: {msg}\n  hint: {hint}\n")})
    }
}

fn error_json(cmd: &str, code: &str, msg: &str, hint: &str) -> String {
    cadcore::error_json(
        cmd,
        code,
        msg,
        hint,
        match code {
            "WORKER_CRASHED" => exit::WORKER_CRASHED,
            "TIMEOUT" => exit::TIMEOUT,
            _ => exit::INTERNAL,
        },
    )
}

fn forward(slot: &mut Slot, key: &str, argv: &[String], cwd: &PathBuf, timeout: Duration) -> Value {
    // a worker that died while idle is replaced transparently: no command was lost
    if let Some(w) = slot.worker.as_mut() {
        if let Ok(Some(status)) = w.child.try_wait() {
            log(&format!(
                "worker pid {} for {key} died while idle ({status}); restarting",
                w.pid
            ));
            slot.crashes += 1;
            slot.worker = None;
        }
    }
    if slot.worker.is_none() {
        match spawn_worker(key) {
            Ok(w) => {
                slot.spawned += 1;
                slot.worker = Some(w);
            }
            Err(e) => {
                return failure(
                    argv,
                    "WORKER_START_FAILED",
                    &e,
                    "check CAD_PYTHON and the daemon log",
                    exit::INTERNAL,
                )
            }
        }
    }
    let w = slot.worker.as_mut().unwrap();
    w.next_id += 1;
    let id = w.next_id;
    let msg = json!({"id": id, "argv": argv, "cwd": cwd}).to_string() + "\n";
    if w.stdin.write_all(msg.as_bytes()).is_err() {
        return crashed(slot, argv);
    }
    w.requests += 1;
    match w.lines.recv_timeout(timeout) {
        Ok(line) => match serde_json::from_str::<Value>(&line) {
            Ok(v) => v,
            Err(e) => failure(
                argv,
                "INTERNAL",
                &format!("bad worker response: {e}"),
                "see the worker log",
                exit::INTERNAL,
            ),
        },
        Err(RecvTimeoutError::Timeout) => {
            if let Some(mut w) = slot.worker.take() {
                let _ = w.child.kill();
                let _ = w.child.wait();
            }
            failure(
                argv,
                "TIMEOUT",
                &format!(
                    "command exceeded {}s; the worker was stopped",
                    timeout.as_secs()
                ),
                "increase --timeout or simplify the model; the last successful revision is intact",
                exit::TIMEOUT,
            )
        }
        Err(RecvTimeoutError::Disconnected) => crashed(slot, argv),
    }
}

fn crashed(slot: &mut Slot, argv: &[String]) -> Value {
    slot.crashes += 1;
    let mut detail = String::new();
    if let Some(mut w) = slot.worker.take() {
        let status = w.child.wait().ok();
        detail = format!(
            "worker pid {} exited ({:?}); last log lines:\n{}",
            w.pid,
            status,
            tail(&w.log, 1500)
        );
    }
    log(&format!("worker crashed: {detail}"));
    failure(argv, "WORKER_CRASHED", &format!("the geometry worker crashed while running this command. {detail}"),
            "the worker restarts automatically on the next command and reloads the last successful revision from disk; \
             if it repeats, the last operation likely triggers a kernel crash",
            exit::WORKER_CRASHED)
}

fn tail(p: &PathBuf, n: u64) -> String {
    let mut f = match fs::File::open(p) {
        Ok(f) => f,
        Err(_) => return String::new(),
    };
    let len = f.metadata().map(|m| m.len()).unwrap_or(0);
    let _ = f.seek(SeekFrom::Start(len.saturating_sub(n)));
    let mut s = String::new();
    let _ = f.read_to_string(&mut s);
    s
}

fn spawn_worker(key: &str) -> Result<Worker, String> {
    let logdir = state_dir().join("logs");
    fs::create_dir_all(&logdir).map_err(|e| e.to_string())?;
    let safe: String = key
        .chars()
        .map(|c| if c.is_ascii_alphanumeric() { c } else { '_' })
        .collect();
    let safe = if safe.len() > 80 {
        safe[safe.len() - 80..].to_string()
    } else {
        safe
    };
    let logp = logdir.join(format!("worker-{safe}.log"));
    let logf = fs::OpenOptions::new()
        .create(true)
        .append(true)
        .open(&logp)
        .map_err(|e| e.to_string())?;
    let mut cmd = Command::new(python());
    cmd.arg("-m")
        .arg("cad.worker")
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(logf);
    let mem_mb: Option<u64> = env::var("CAD_WORKER_MAX_MEM_MB")
        .ok()
        .and_then(|v| v.parse().ok());
    let cpu_s: Option<u64> = env::var("CAD_WORKER_CPU_SECS")
        .ok()
        .and_then(|v| v.parse().ok());
    unsafe {
        cmd.pre_exec(move || {
            if let Some(mb) = mem_mb {
                let lim = libc::rlimit {
                    rlim_cur: mb * 1024 * 1024,
                    rlim_max: mb * 1024 * 1024,
                };
                libc::setrlimit(libc::RLIMIT_AS, &lim);
            }
            if let Some(s) = cpu_s {
                let lim = libc::rlimit {
                    rlim_cur: s,
                    rlim_max: s + 5,
                };
                libc::setrlimit(libc::RLIMIT_CPU, &lim);
            }
            Ok(())
        });
    }
    let mut child = cmd
        .spawn()
        .map_err(|e| format!("cannot start {}: {e}", python().display()))?;
    let stdin = child.stdin.take().unwrap();
    let stdout = child.stdout.take().unwrap();
    let (tx, rx) = channel();
    std::thread::spawn(move || {
        for line in BufReader::new(stdout).lines() {
            match line {
                Ok(l) => {
                    if tx.send(l).is_err() {
                        break;
                    }
                }
                Err(_) => break,
            }
        }
    });
    let ready = rx
        .recv_timeout(Duration::from_secs(60))
        .map_err(|_| format!("worker did not start; see {}", logp.display()))?;
    let v: Value =
        serde_json::from_str(&ready).map_err(|e| format!("bad worker handshake: {e}"))?;
    if v["ready"] != json!(true) {
        return Err(format!("unexpected worker handshake: {ready}"));
    }
    log(&format!(
        "worker for {key} started pid {} in {}ms",
        child.id(),
        v["startup_ms"]
    ));
    Ok(Worker {
        pid: child.id(),
        child,
        stdin,
        lines: rx,
        started: Instant::now(),
        requests: 0,
        log: logp,
        next_id: 0,
    })
}

fn status(d: &Daemon) -> Value {
    let slots: Vec<(String, Arc<Mutex<Slot>>)> = d
        .slots
        .lock()
        .unwrap()
        .iter()
        .map(|(k, v)| (k.clone(), v.clone()))
        .collect();
    let mut workers = vec![];
    for (k, s) in slots {
        let entry = match s.try_lock() {
            Ok(mut slot) => {
                let (restarts, crashes) = (slot.spawned.saturating_sub(1), slot.crashes);
                match slot.worker.as_mut() {
                    Some(w) => {
                        w.next_id += 1;
                        let ping = json!({"id": w.next_id, "op": "ping"}).to_string() + "\n";
                        let info = if w.stdin.write_all(ping.as_bytes()).is_ok() {
                            w.lines
                                .recv_timeout(Duration::from_secs(5))
                                .ok()
                                .and_then(|l| serde_json::from_str::<Value>(&l).ok())
                        } else {
                            None
                        };
                        let info = info.unwrap_or(json!({}));
                        json!({"session": k, "pid": w.pid, "uptime_s": w.started.elapsed().as_secs(), "requests": w.requests,
                               "restarts": restarts, "crashes": crashes, "busy": false,
                               "max_rss_kb": info["max_rss_kb"], "stats": info["sessions"]})
                    }
                    None => {
                        json!({"session": k, "pid": null, "requests": 0, "restarts": restarts, "crashes": crashes, "busy": false})
                    }
                }
            }
            Err(_) => json!({"session": k, "busy": true}),
        };
        workers.push(entry);
    }
    json!({"pid": std::process::id(), "uptime_s": d.started.elapsed().as_secs(), "socket": d.sock,
           "cadd": d.exe, "build": d.build, "python": python(), "workers": workers})
}
