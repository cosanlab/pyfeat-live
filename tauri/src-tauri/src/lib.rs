// Tauri shell for pyfeatlive.
//
// Architecture:
//   - The .app bundles `uv` (Astral) as an externalBin and the
//     pyfeatlive Python source + sidecar.py + requirements.txt as
//     resources. It does NOT bundle a Python interpreter or the
//     ML dependency tree.
//   - On first launch, the shell uses the bundled uv to install a
//     standalone Python + the runtime requirements into the OS-
//     standard application-data directory. ~1.5GB on disk; only
//     happens once unless the requirements lock changes.
//   - On every launch, the shell spawns sidecar.py from the user-
//     installed venv and points the WebView at the FastAPI (uvicorn)
//     localhost server it serves.
//   - In dev mode (`tauri dev`) we skip the bootstrap and use the
//     repo's `.venv/bin/python` directly, so iteration is fast.

use std::path::{Path, PathBuf};
use std::process::Stdio;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{Arc, Mutex};

use serde::Serialize;
use tauri::menu::{MenuBuilder, MenuItem, SubmenuBuilder};
use tauri::{
    AppHandle, Emitter, Manager, RunEvent, WebviewUrl, WebviewWindowBuilder,
};
use tauri_plugin_updater::UpdaterExt;
use tokio::io::{AsyncBufReadExt, BufReader};
use tokio::process::{Child, Command};

#[cfg(target_os = "macos")]
mod macos_camera;

/// Preferred sidecar ports. A DETERMINISTIC range (not an OS-assigned
/// ephemeral port) so the SPA origin http://127.0.0.1:<port> — and with it
/// the webview's per-origin localStorage (overlay style, experimental
/// flags, dismissed update banners) — stays stable across launches. The v1
/// prototype's fixed 8501 collided with Streamlit's default; this range has
/// no common squatter, a second app instance simply takes the next port,
/// and the identity-checked health probe (backend_healthy) refuses to
/// navigate into anything that isn't our sidecar. If the whole range is
/// somehow taken we fall back to an ephemeral port (costs stored settings
/// for that launch — acceptable over failing to start).
const SIDECAR_PORT_RANGE: std::ops::Range<u16> = 18640..18650;

static SIDECAR_PORT_CELL: std::sync::OnceLock<u16> = std::sync::OnceLock::new();

/// Pick the sidecar port. Called for the FIRST time right before spawning
/// the sidecar (NOT at window creation) so the probe→bind window is
/// milliseconds — previously the pick happened before the first-run
/// runtime install, leaving the port unreserved for minutes.
fn sidecar_port() -> u16 {
    *SIDECAR_PORT_CELL.get_or_init(|| {
        for port in SIDECAR_PORT_RANGE {
            if std::net::TcpListener::bind(("127.0.0.1", port)).is_ok() {
                return port;
            }
        }
        std::net::TcpListener::bind(("127.0.0.1", 0))
            .and_then(|l| l.local_addr())
            .map(|a| a.port())
            .unwrap_or(18650)
    })
}

/// Frontend event names. Keep in sync with tauri/dist/setup.html.
const EVENT_BOOTSTRAP_LOG: &str = "bootstrap://log";
const EVENT_BOOTSTRAP_DONE: &str = "bootstrap://done";
const EVENT_BOOTSTRAP_ERROR: &str = "bootstrap://error";

/// Holds the spawned sidecar handle so we can kill it on app exit.
/// Wrapped in Mutex<Option<>> because Tauri's State requires Sync.
struct SidecarState(Mutex<Option<Child>>);

#[derive(Serialize, Clone)]
struct LogPayload {
    stream: &'static str, // "stdout" | "stderr"
    line: String,
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    env_logger::init();

    tauri::Builder::default()
        .plugin(tauri_plugin_updater::Builder::new().build())
        .plugin(tauri_plugin_process::init())
        .plugin(tauri_plugin_dialog::init())
        .manage(SidecarState(Mutex::new(None)))
        .invoke_handler(tauri::generate_handler![apply_update, restart_app])
        .setup(|app| {
            // Window first so the splash is visible while the install runs.
            // The splash (setup.html) polls the backend and redirects once
            // it's serving (the Rust shell also drives the redirect). We do
            // NOT call sidecar_port() here — that would pick (and reserve)
            // the port at window-creation time, before the first-run
            // runtime install, leaving it unbound and stealable for
            // minutes. The splash instead learns the port from the
            // `bootstrap://done` event payload, emitted right before spawn.
            let window = WebviewWindowBuilder::new(
                app,
                "main",
                WebviewUrl::App("setup.html".into()),
            )
            .title("Py-feat Live")
            // Conservative default that fits small laptops (a 1280x800 screen
            // couldn't show the old 1280x800 window once the menu bar/title
            // bar are accounted for — it opened partly off-screen). Centered
            // and resizable, so larger displays can grow it.
            .inner_size(1100.0, 720.0)
            .min_inner_size(900.0, 600.0)
            .resizable(true)
            .center()
            // Tauri intercepts OS file drops by default, which swallows the
            // webview's HTML5 drag-and-drop events — the Extract dropzone
            // never received them. Disable the native handler so the page's
            // ondrop/ondragover fire normally.
            .disable_drag_drop_handler()
            .build()?;

            // macOS only: install our WKUIDelegate that auto-grants
            // getUserMedia permission once the OS has approved the
            // parent app for camera access. Works around the
            // "permission prompt never appears in WebView" bug
            // (Tauri #11951 / wry #1195). No-op on other platforms.
            #[cfg(target_os = "macos")]
            {
                let _ = window.with_webview(|webview| {
                    // SAFETY: webview.inner() returns a valid WKWebView
                    // pointer on macOS for the duration of this callback.
                    unsafe {
                        macos_camera::install_media_delegate(webview.inner());
                    }
                });
            }
            #[cfg(not(target_os = "macos"))]
            {
                let _ = window;
            }

            // Native application menu. The shell shipped without one, so the
            // only update prompt was the launch-time banner. This adds an
            // explicit "Check for Updates…" item to the app menu.
            //
            // A custom menu *replaces* Tauri's default, which would otherwise
            // drop the cut/copy/paste keyboard shortcuts — so we rebuild the
            // standard Edit/Window submenus too. The macOS-only predefined
            // items (services/hide/fullscreen) are cfg-gated so non-macOS
            // builds stay green.
            //
            // We deliberately don't run the update check here: the frontend
            // owns the update lifecycle (it holds the pending Update handle
            // the install button needs), so the menu just pokes it via
            // `menu://check-for-updates` and the UpdateBanner re-runs its own
            // check.
            let settings = MenuItem::with_id(
                app,
                "settings",
                "Settings…",
                true,
                Some("CmdOrCtrl+,"),
            )?;
            let check_updates = MenuItem::with_id(
                app,
                "check-for-updates",
                "Check for Updates…",
                true,
                None::<&str>,
            )?;
            let mut app_menu = SubmenuBuilder::new(app, "Py-feat")
                .about(None)
                .separator()
                .item(&settings)
                .separator()
                .item(&check_updates)
                .separator();
            #[cfg(target_os = "macos")]
            {
                app_menu = app_menu
                    .services()
                    .separator()
                    .hide()
                    .hide_others()
                    .show_all()
                    .separator();
            }
            let app_menu = app_menu.quit().build()?;

            let edit_menu = SubmenuBuilder::new(app, "Edit")
                .undo()
                .redo()
                .separator()
                .cut()
                .copy()
                .paste()
                .select_all()
                .build()?;

            let mut window_menu = SubmenuBuilder::new(app, "Window").minimize();
            #[cfg(target_os = "macos")]
            {
                window_menu = window_menu.fullscreen();
            }
            let window_menu = window_menu.separator().close_window().build()?;

            let menu = MenuBuilder::new(app)
                .items(&[&app_menu, &edit_menu, &window_menu])
                .build()?;
            app.set_menu(menu)?;
            app.on_menu_event(|app, event| {
                match event.id().0.as_str() {
                    "check-for-updates" => {
                        let _ = app.emit("menu://check-for-updates", ());
                    }
                    "settings" => {
                        let _ = app.emit("menu://settings", ());
                    }
                    _ => {}
                }
            });

            let handle = app.handle().clone();
            tauri::async_runtime::spawn(async move {
                if let Err(e) = bootstrap_and_launch(&handle).await {
                    log::error!("startup failed: {e}");
                    let _ = handle.emit(EVENT_BOOTSTRAP_ERROR, e.to_string());
                }
            });

            // Background self-update check. Runs in parallel with the
            // bootstrap so a slow network doesn't gate launch. We only
            // *notify* the user on a found update — the splash subscribes
            // to "updater://available" and surfaces a "Update available"
            // banner that the user can click to apply. We never auto-
            // apply during a session because that would yank the
            // sidecar subprocess out from under the user.
            let updater_handle = app.handle().clone();
            tauri::async_runtime::spawn(async move {
                if let Err(e) = check_for_update(&updater_handle).await {
                    // Network failures here are non-fatal — log only.
                    log::info!("updater check skipped: {e}");
                }
            });

            Ok(())
        })
        .build(tauri::generate_context!())
        .expect("error while building tauri application")
        .run(|app_handle, event| {
            // Kill the sidecar on app exit. ExitRequested fires before
            // the process is torn down — last chance to send SIGTERM.
            if let RunEvent::ExitRequested { .. } = event {
                if let Some(mut child) = app_handle
                    .state::<SidecarState>()
                    .0
                    .lock()
                    .unwrap()
                    .take()
                {
                    let _ = child.start_kill();
                }
            }
        });
}

async fn bootstrap_and_launch(app: &AppHandle) -> Result<(), String> {
    // Resolve the install target dir under the OS-standard app-data
    // location:
    //   macOS:   ~/Library/Application Support/com.cosanlab.pyfeatlive/
    //   Windows: %APPDATA%/com.cosanlab.pyfeatlive/
    //   Linux:   ~/.local/share/com.cosanlab.pyfeatlive/
    let data_dir = app
        .path()
        .app_data_dir()
        .map_err(|e| format!("could not resolve app data dir: {e}"))?;
    let runtime_dir = data_dir.join("runtime");
    let venv_dir = runtime_dir.join("venv");
    std::fs::create_dir_all(&runtime_dir)
        .map_err(|e| format!("could not create {}: {e}", runtime_dir.display()))?;

    // HuggingFace cache lives next to the runtime so an "uninstall"
    // can nuke the whole tree in one rm -rf.
    let cache_dir = app
        .path()
        .app_cache_dir()
        .map_err(|e| format!("could not resolve app cache dir: {e}"))?;
    let hf_home = cache_dir.join("huggingface");
    std::fs::create_dir_all(&hf_home).ok();

    let python_path = venv_python(&venv_dir);

    // (Re)install the Python runtime when needed. Skip entirely in dev (we
    // use the repo's .venv). In prod we install on first run AND whenever
    // the bundled requirements.txt differs from what's currently installed
    // — a stamp file records the requirements we last installed. Without
    // this, upgrading the app reused a stale venv: a pre-FastAPI install
    // was missing `fastapi`, so the sidecar crashed on import and the
    // backend never came up.
    if !cfg!(debug_assertions) {
        let resource_dir = app
            .path()
            .resource_dir()
            .map_err(|e| format!("could not resolve resource dir: {e}"))?;
        let requirements = resource_dir.join("runtime/requirements.txt");
        if needs_install(&python_path, &runtime_dir, &requirements) {
            // Remove a stale venv so a dependency change yields a clean
            // tree (drops packages that were removed across versions).
            if venv_dir.exists() {
                emit_log(app, "stdout", "Dependencies changed — rebuilding the Python runtime…");
                std::fs::remove_dir_all(&venv_dir)
                    .map_err(|e| format!("could not remove stale venv: {e}"))?;
            }
            run_bootstrap(app, &runtime_dir, &venv_dir).await?;
            // Record what we just installed so future changes are detected.
            if let Ok(bytes) = std::fs::read(&requirements) {
                let _ = std::fs::write(requirements_stamp_path(&runtime_dir), bytes);
            }
        }
    }

    // Resolve which Python to spawn:
    //   - dev:  $REPO/.venv/bin/python  (no bootstrap; fast iteration)
    //   - prod: <app-data>/runtime/venv/bin/python
    let (python, sidecar_script, pyfeatlive_root) = if cfg!(debug_assertions) {
        let repo_root = dev_repo_root();
        (
            repo_root.join(".venv/bin/python"),
            repo_root.join("sidecar/sidecar.py"),
            repo_root.clone(),
        )
    } else {
        let resource_dir = app
            .path()
            .resource_dir()
            .map_err(|e| format!("could not resolve resource dir: {e}"))?;
        (
            python_path.clone(),
            resource_dir.join("runtime/sidecar.py"),
            resource_dir,
        )
    };

    // Spawn the sidecar. We use std::process via tokio because Tauri
    // v2's shell plugin path is for letting JS spawn commands; we're
    // doing it from Rust, so the std API is simpler.
    let mut cmd = Command::new(&python);
    cmd.arg(&sidecar_script)
        .arg("--port")
        .arg(sidecar_port().to_string())
        .arg("--address")
        .arg("127.0.0.1")
        .env("OMP_NUM_THREADS", "1")
        .env("HF_HOME", &hf_home)
        // PYTHONPATH so sidecar.py can import the backend + pyfeatlive_core
        // packages from the bundle resources (or repo root in dev).
        .env("PYTHONPATH", &pyfeatlive_root)
        .stdout(Stdio::piped())
        .stderr(Stdio::piped());

    let mut child = cmd
        .spawn()
        .map_err(|e| format!("failed to spawn sidecar: {e}"))?;

    // Drain stdout/stderr to: the app log always, and — only during the startup
    // window — the splash (so a startup crash is VISIBLE instead of an
    // indefinite spinner) and a per-launch log file. `startup_logging` flips off
    // once the backend is healthy, so a busy Live session's app logs don't pay a
    // splash-emit + file open/append per line.
    let log_path = sidecar_log_path(app);
    let _ = std::fs::File::create(&log_path); // truncate: keep only this launch's startup output
    let startup_logging = Arc::new(AtomicBool::new(true));
    emit_log(app, "stdout", &format!("sidecar log: {}", log_path.display()));
    if let Some(stdout) = child.stdout.take() {
        forward_to_log(stdout, "sidecar/stdout", app.clone(), "stdout", log_path.clone(), startup_logging.clone());
    }
    if let Some(stderr) = child.stderr.take() {
        forward_to_log(stderr, "sidecar/stderr", app.clone(), "stderr", log_path.clone(), startup_logging.clone());
    }

    // Stash the handle so RunEvent::ExitRequested can kill it.
    *app.state::<SidecarState>().0.lock().unwrap() = Some(child);

    // Tell the splash the runtime install finished. setup.html streams the
    // bootstrap logs and, as a *fallback*, polls /api/system/health to
    // redirect itself.
    app.emit(EVENT_BOOTSTRAP_DONE, sidecar_port())
        .map_err(|e| format!("could not emit bootstrap-done: {e}"))?;

    // Primary handoff: poll the backend natively (no webview / CORS involvement)
    // and navigate the window to it once it serves — the robust path that
    // doesn't depend on WebKit's cross-origin fetch behavior. The loop never
    // stops trying to navigate (a backend that comes up late is still picked
    // up); it only surfaces an error so the user isn't staring at a bare
    // spinner — immediately if the sidecar process exits (crash, terminal), or
    // once after a generous deadline if it's alive but not yet serving.
    let nav_handle = app.clone();
    let nav_logging = startup_logging.clone();
    tauri::async_runtime::spawn(async move {
        let deadline = tokio::time::Instant::now() + std::time::Duration::from_secs(600);
        let mut deadline_reported = false;
        loop {
            if backend_healthy(sidecar_port()).await {
                nav_logging.store(false, Ordering::Relaxed); // backend up — stop splash/file forwarding
                if let Some(window) = nav_handle.get_webview_window("main") {
                    match tauri::Url::parse(&format!("http://127.0.0.1:{}/", sidecar_port())) {
                        Ok(url) => {
                            if let Err(e) = window.navigate(url) {
                                log::error!("navigate to backend failed: {e}");
                            }
                        }
                        Err(e) => log::error!("bad backend url: {e}"),
                    }
                }
                return;
            }
            // Sidecar exited (crash) before serving — terminal. Surface it now
            // rather than waiting out the deadline on a dead process.
            let exited = {
                let state = nav_handle.state::<SidecarState>();
                let mut guard = state.0.lock().unwrap();
                guard.as_mut().and_then(|c| c.try_wait().ok().flatten())
            };
            if let Some(status) = exited {
                log::error!("sidecar exited before serving: {status}");
                nav_logging.store(false, Ordering::Relaxed);
                let _ = nav_handle.emit(
                    EVENT_BOOTSTRAP_ERROR,
                    format!("The backend process stopped unexpectedly ({status}). See the log below."),
                );
                return;
            }
            // Alive but not serving yet. After a generous deadline surface an
            // actionable error ONCE — but keep polling, so a merely-slow backend
            // is still navigated to when it finally comes up.
            if !deadline_reported && tokio::time::Instant::now() >= deadline {
                deadline_reported = true;
                log::error!("backend not healthy within deadline; still waiting");
                let _ = nav_handle.emit(
                    EVENT_BOOTSTRAP_ERROR,
                    "The backend is taking longer than expected to start. Keep waiting, or restart. See the log below.".to_string(),
                );
            }
            tokio::time::sleep(std::time::Duration::from_millis(500)).await;
        }
    });

    Ok(())
}

/// One health probe: minimal HTTP/1.0 GET against /api/system/health.
/// Requires BOTH a 200 and our own identity marker in the body — a bare
/// 200 check would accept any localhost service squatting on the port
/// and navigate the webview (with its IPC grants) into a foreign page.
/// The whole probe is bounded by a short timeout so a squatting service
/// that accepts but never closes the connection can't hang the startup
/// loop (read_to_end only returns on peer close).
async fn backend_healthy(port: u16) -> bool {
    tokio::time::timeout(std::time::Duration::from_secs(2), async {
        use tokio::io::{AsyncReadExt, AsyncWriteExt};
        let Ok(mut stream) = tokio::net::TcpStream::connect(("127.0.0.1", port)).await else {
            return false;
        };
        let req = format!(
            "GET /api/system/health HTTP/1.0\r\nHost: 127.0.0.1:{port}\r\nConnection: close\r\n\r\n"
        );
        if stream.write_all(req.as_bytes()).await.is_err() {
            return false;
        }
        let mut resp = Vec::with_capacity(512);
        if stream.read_to_end(&mut resp).await.is_err() {
            return false;
        }
        let text = String::from_utf8_lossy(&resp);
        text.starts_with("HTTP/1.")
            && text.contains(" 200 ")
            && text.contains("\"app\":\"pyfeatlive\"")
    })
    .await
    .unwrap_or(false)
}

/// Path of the stamp file recording the requirements.txt we last installed.
fn requirements_stamp_path(runtime_dir: &Path) -> PathBuf {
    runtime_dir.join(".requirements-stamp")
}

/// Whether the Python runtime needs (re)installing: when the venv's python
/// is missing, when no stamp exists (older install), or when the bundled
/// requirements.txt differs from the stamped one. The stamp stores the
/// exact requirements.txt bytes so any change forces a clean reinstall.
fn needs_install(python_path: &Path, runtime_dir: &Path, requirements: &Path) -> bool {
    if !python_path.exists() {
        return true;
    }
    match (
        std::fs::read(requirements),
        std::fs::read(requirements_stamp_path(runtime_dir)),
    ) {
        (Ok(want), Ok(have)) => want != have,
        // Missing stamp or unreadable requirements → reinstall to be safe.
        _ => true,
    }
}

async fn run_bootstrap(
    app: &AppHandle,
    runtime_dir: &Path,
    venv_dir: &Path,
) -> Result<(), String> {
    // First-run install: uv venv + uv pip install. Total ~1.5GB on
    // disk, ~5-10 min on a typical broadband connection.
    let uv_path = uv_binary_path(app)?;
    let resource_dir = app
        .path()
        .resource_dir()
        .map_err(|e| format!("could not resolve resource dir: {e}"))?;
    let requirements = resource_dir.join("runtime/requirements.txt");

    // 1. Create the venv with a uv-managed standalone Python 3.12.
    emit_log(app, "stdout", "Creating Python 3.12 runtime…");
    run_uv(
        app,
        &uv_path,
        runtime_dir,
        &[
            "venv",
            "--python",
            "3.12",
            venv_dir.to_string_lossy().as_ref(),
        ],
    )
    .await?;

    // 2. Install the pinned dependency tree. Most of the time goes here.
    //
    // We do NOT pass --require-hashes because py-feat is pinned to a
    // git SHA (`git+https://github.com/cosanlab/py-feat@<sha>`) and
    // uv pip compile can't generate a hash for git refs — strict mode
    // would refuse to install. uv still validates hashes for *every*
    // entry that has them (~all of PyPI), so we keep tamper protection
    // for the long tail; only py-feat itself relies on git-SHA pinning
    // for trust. When py-feat publishes a wheel to PyPI we can switch
    // and re-enable --require-hashes.
    emit_log(app, "stdout", "Installing dependencies (this takes ~5–10 min on first run)…");
    let py = venv_python(venv_dir);
    run_uv(
        app,
        &uv_path,
        runtime_dir,
        &[
            "pip",
            "install",
            "--python",
            py.to_string_lossy().as_ref(),
            "--requirement",
            requirements.to_string_lossy().as_ref(),
        ],
    )
    .await?;

    Ok(())
}

async fn run_uv(
    app: &AppHandle,
    uv_path: &Path,
    cwd: &Path,
    args: &[&str],
) -> Result<(), String> {
    let mut child = Command::new(uv_path)
        .args(args)
        .current_dir(cwd)
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .spawn()
        .map_err(|e| format!("failed to spawn uv {args:?}: {e}"))?;

    // Stream both pipes concurrently to the splash UI.
    let stdout = child.stdout.take().expect("stdout piped");
    let stderr = child.stderr.take().expect("stderr piped");
    let app_out = app.clone();
    let app_err = app.clone();
    let h1 = tokio::spawn(async move { stream_to_event(&app_out, "stdout", stdout).await });
    let h2 = tokio::spawn(async move { stream_to_event(&app_err, "stderr", stderr).await });

    let status = child
        .wait()
        .await
        .map_err(|e| format!("waiting on uv: {e}"))?;
    let _ = h1.await;
    let _ = h2.await;

    if !status.success() {
        return Err(format!("uv {args:?} exited with {status}"));
    }
    Ok(())
}

async fn stream_to_event<R: tokio::io::AsyncRead + Unpin>(
    app: &AppHandle,
    stream: &'static str,
    reader: R,
) {
    let mut buf = BufReader::new(reader).lines();
    while let Ok(Some(line)) = buf.next_line().await {
        log::info!("uv/{stream}: {line}");
        let _ = app.emit(EVENT_BOOTSTRAP_LOG, LogPayload { stream, line });
    }
}

fn emit_log(app: &AppHandle, stream: &'static str, msg: &str) {
    log::info!("bootstrap/{stream}: {msg}");
    let _ = app.emit(
        EVENT_BOOTSTRAP_LOG,
        LogPayload {
            stream,
            line: msg.to_string(),
        },
    );
}

fn forward_to_log<R>(
    reader: R,
    tag: &'static str,
    app: AppHandle,
    stream: &'static str,
    log_path: PathBuf,
    startup_logging: Arc<AtomicBool>,
) where
    R: tokio::io::AsyncRead + Unpin + Send + 'static,
{
    tauri::async_runtime::spawn(async move {
        let mut buf = BufReader::new(reader).lines();
        while let Ok(Some(line)) = buf.next_line().await {
            log::info!("{tag}: {line}");
            // Only during startup: mirror to the splash (so a startup failure is
            // visible — exactly when it happens) and the per-launch log file.
            // Flips off once the backend is healthy, so a busy Live session
            // doesn't pay a splash-emit + file open/append for every line.
            if startup_logging.load(Ordering::Relaxed) {
                let _ = app.emit(EVENT_BOOTSTRAP_LOG, LogPayload { stream, line: line.clone() });
                append_log_line(&log_path, &line);
            }
        }
    });
}

/// Append a line to the sidecar log file, best-effort (a logging failure must
/// never take down startup).
fn append_log_line(path: &Path, line: &str) {
    use std::io::Write;
    if let Ok(mut f) = std::fs::OpenOptions::new().create(true).append(true).open(path) {
        let _ = writeln!(f, "{line}");
    }
}

/// Path to the persistent sidecar log (`~/Library/Logs/<bundle>/sidecar.log` on
/// macOS). Creates the directory; falls back to the temp dir if it can't be
/// resolved. Users can be pointed here to retrieve a startup traceback.
fn sidecar_log_path(app: &AppHandle) -> PathBuf {
    let dir = app.path().app_log_dir().unwrap_or_else(|_| std::env::temp_dir());
    let _ = std::fs::create_dir_all(&dir);
    dir.join("sidecar.log")
}

fn venv_python(venv_dir: &Path) -> PathBuf {
    if cfg!(target_os = "windows") {
        venv_dir.join("Scripts/python.exe")
    } else {
        venv_dir.join("bin/python")
    }
}

/// Find the bundled `uv` binary. Tauri's `externalBin` copies it into
/// the app bundle at build time. Naming differs by build mode:
///   - `tauri build` (release):
///       macOS:   Contents/MacOS/uv  (triple suffix stripped)
///       Linux:   <install>/uv       (triple suffix stripped)
///       Windows: <install>/uv.exe
///   - `tauri dev` (debug, no bundle):
///       target/<profile>/uv-<triple>  (triple suffix preserved)
///       so the dev-cycle round-trip can still find it.
fn uv_binary_path(app: &AppHandle) -> Result<PathBuf, String> {
    let triple = host_triple();
    let exe_name = if cfg!(target_os = "windows") { "uv.exe" } else { "uv" };
    let resource_dir = app
        .path()
        .resource_dir()
        .map_err(|e| format!("could not resolve resource dir: {e}"))?;

    let mut candidates = Vec::new();
    // macOS bundle: Contents/MacOS/<exe>
    if let Some(p) = resource_dir.parent() {
        candidates.push(p.join("MacOS").join(exe_name));
        candidates.push(p.join("MacOS").join(format!("uv-{triple}")));
    }
    // Linux / Windows install root: same dir as main exe
    candidates.push(resource_dir.join(exe_name));
    candidates.push(resource_dir.join(format!("uv-{triple}")));
    // Dev runs: cargo target dir alongside the tauri binary
    if let Some(exe_dir) = std::env::current_exe()
        .ok()
        .and_then(|p| p.parent().map(PathBuf::from))
    {
        candidates.push(exe_dir.join(exe_name));
        candidates.push(exe_dir.join(format!("uv-{triple}")));
    }

    for c in &candidates {
        if c.exists() {
            return Ok(c.clone());
        }
    }
    Err(format!(
        "could not find bundled uv (tried: {})",
        candidates
            .iter()
            .map(|p| p.display().to_string())
            .collect::<Vec<_>>()
            .join(", ")
    ))
}

/// Check the configured updater endpoint for a newer release. Emits
/// `updater://available` (with the new version + release notes) on
/// hit, `updater://up-to-date` otherwise. We never download or apply
/// in this function — the user has to opt in by clicking the banner
/// the splash renders, which then calls a separate "apply update"
/// command (TODO: expose via `#[tauri::command]` once the splash UI
/// has a button for it).
async fn check_for_update(app: &AppHandle) -> Result<(), String> {
    let updater = app
        .updater()
        .map_err(|e| format!("updater plugin not initialised: {e}"))?;
    match updater
        .check()
        .await
        .map_err(|e| format!("update check failed: {e}"))?
    {
        Some(update) => {
            let payload = serde_json::json!({
                "version": update.version,
                "current_version": update.current_version,
                "body": update.body.clone().unwrap_or_default(),
            });
            let _ = app.emit("updater://available", payload);
            log::info!(
                "update available: {} -> {}",
                update.current_version,
                update.version
            );
        }
        None => {
            let _ = app.emit("updater://up-to-date", ());
            log::info!("no update available");
        }
    }
    Ok(())
}

/// Relaunch the app. Backs the splash "Restart" button when the backend
/// fails to start, so the user can retry without hunting for the app in Finder.
#[tauri::command]
fn restart_app(app: AppHandle) {
    app.restart();
}

/// Download, verify, and install the pending update, then relaunch into
/// it. Invoked from the splash "Update & Restart" button. Re-runs the
/// check to obtain a fresh `Update` handle (cheap — one HTTPS request),
/// streams download progress to the splash via `updater://progress`
/// ({downloaded, total}), emits `updater://installing` once the bytes
/// are in, then restarts. `restart()` triggers RunEvent::ExitRequested,
/// which kills the sidecar, before relaunching the freshly-installed
/// bundle.
#[tauri::command]
async fn apply_update(app: AppHandle) -> Result<(), String> {
    let updater = app
        .updater()
        .map_err(|e| format!("updater plugin not initialised: {e}"))?;
    let update = updater
        .check()
        .await
        .map_err(|e| format!("update check failed: {e}"))?
        .ok_or_else(|| "no update available".to_string())?;

    let progress_app = app.clone();
    let finish_app = app.clone();
    let mut downloaded: usize = 0;
    update
        .download_and_install(
            move |chunk, total| {
                downloaded += chunk;
                let _ = progress_app.emit(
                    "updater://progress",
                    serde_json::json!({ "downloaded": downloaded, "total": total }),
                );
            },
            move || {
                let _ = finish_app.emit("updater://installing", ());
            },
        )
        .await
        .map_err(|e| format!("download/install failed: {e}"))?;

    // Relaunch into the freshly-installed version. `restart()` diverges
    // (returns `!`), so it's the trailing expression — nothing runs after.
    app.restart()
}

/// Compile-time host triple.
const fn host_triple() -> &'static str {
    // Constant for the platform Tauri bundled the .app for. Mirrors
    // what `rustc -vV | grep host` returned at build time.
    #[cfg(all(target_arch = "aarch64", target_os = "macos"))]
    {
        "aarch64-apple-darwin"
    }
    #[cfg(all(target_arch = "x86_64", target_os = "macos"))]
    {
        "x86_64-apple-darwin"
    }
    #[cfg(all(target_arch = "x86_64", target_os = "windows"))]
    {
        "x86_64-pc-windows-msvc"
    }
    #[cfg(all(target_arch = "x86_64", target_os = "linux"))]
    {
        "x86_64-unknown-linux-gnu"
    }
    #[cfg(all(target_arch = "aarch64", target_os = "linux"))]
    {
        "aarch64-unknown-linux-gnu"
    }
}

/// Walk up from the running tauri binary to the repo root, used in
/// dev mode to find the repo's .venv and sidecar/sidecar.py.
fn dev_repo_root() -> PathBuf {
    // tauri/src-tauri/target/debug/<binary>
    //   ancestors:
    //     0: <binary>
    //     1: target/debug/
    //     2: target/
    //     3: src-tauri/
    //     4: tauri/
    //     5: <repo root>
    let exe = std::env::current_exe().expect("current_exe");
    exe.ancestors()
        .nth(5)
        .map(PathBuf::from)
        .unwrap_or_else(|| PathBuf::from("."))
}
