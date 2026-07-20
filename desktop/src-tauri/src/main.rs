// Prevent a console window on Windows release builds.
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

//! Yunaki desktop shell (Tauri 2).
//!
//! Lifecycle on launch:
//!   1. reserve a free loopback port and mint a per-launch bearer token (uuid),
//!   2. spawn the FastAPI sidecar bound to 127.0.0.1:<port> with `--token`,
//!   3. poll GET /api/health (with the token) until it is ready,
//!   4. create the main window, injecting `window.__YUNAKI_API__ = {base, token}`
//!      via an init script that runs before the page's own scripts,
//!   5. load the exported Next frontend (frontendDist) from the app bundle,
//!   6. kill the sidecar when the app exits.
//!
//! The token lives only in process memory + the injected object; it is never
//! persisted or logged. GEMINI_API_KEY (and any other backend secret) flows to
//! the sidecar through inherited process env — see resolve_sidecar / README.
//! Keychain-backed secret injection is Phase E2.

use std::process::{Child, Command};
use std::sync::Mutex;
use std::time::{Duration, Instant};

use tauri::{Manager, RunEvent, WebviewUrl, WebviewWindowBuilder};

/// Handle to the spawned sidecar, kept in managed state so the exit handler can
/// reap it.
struct SidecarProcess(Mutex<Option<Child>>);

/// Reserve a free loopback port by binding to :0 and releasing it. There is a
/// small race before the sidecar re-binds, acceptable for a single-user app.
fn pick_free_port() -> u16 {
    std::net::TcpListener::bind("127.0.0.1:0")
        .expect("failed to reserve a loopback port")
        .local_addr()
        .expect("failed to read reserved port")
        .port()
}

/// The webview's own origin, which the sidecar must allow via CORS. Tauri v2
/// serves the bundled frontend from a per-platform scheme. Overridable with
/// YUNAKI_FRONTEND_ORIGIN for unusual setups.
fn webview_origin() -> String {
    if let Ok(origin) = std::env::var("YUNAKI_FRONTEND_ORIGIN") {
        return origin;
    }
    if cfg!(target_os = "windows") {
        "http://tauri.localhost".to_string()
    } else {
        "tauri://localhost".to_string()
    }
}

/// Build the sidecar launch command.
///
/// - Release: the PyInstaller one-dir binary bundled as a resource.
/// - Debug (`tauri dev`): `YUNAKI_SIDECAR_BIN` if set (a pre-built binary),
///   otherwise run `desktop_entry.py` straight from the backend venv so the dev
///   loop needs no prior PyInstaller freeze.
///
/// Process env is inherited, so GEMINI_API_KEY / SUPABASE_* set in the shell's
/// environment reach the sidecar unchanged.
// `app` is used only in the release branch (bundled-resource path resolution);
// debug builds resolve from CARGO_MANIFEST_DIR, so it is unused there.
#[cfg_attr(debug_assertions, allow(unused_variables))]
fn resolve_sidecar(app: &tauri::App, port: u16, token: &str) -> Command {
    let origin = webview_origin();
    let port_s = port.to_string();

    #[cfg(debug_assertions)]
    {
        if let Ok(bin) = std::env::var("YUNAKI_SIDECAR_BIN") {
            let mut c = Command::new(bin);
            c.args(["--port", &port_s, "--token", token]);
            c.env("FRONTEND_ORIGIN", &origin);
            return c;
        }
        // <repo>/desktop/src-tauri  ->  up two  ->  <repo>
        let repo = std::path::Path::new(env!("CARGO_MANIFEST_DIR"))
            .parent()
            .and_then(|p| p.parent())
            .expect("cannot resolve repo root");
        let py = repo.join("backend/.venv/bin/python");
        let entry = repo.join("backend/desktop_entry.py");
        let mut c = Command::new(py);
        c.arg(entry);
        c.args(["--port", &port_s, "--token", token]);
        c.env("FRONTEND_ORIGIN", &origin);
        c.current_dir(repo.join("backend"));
        return c;
    }

    #[cfg(not(debug_assertions))]
    {
        let bin = app
            .path()
            .resource_dir()
            .expect("no resource dir")
            .join("yunaki-sidecar")
            .join("yunaki-sidecar");
        let mut c = Command::new(bin);
        c.args(["--port", &port_s, "--token", token]);
        c.env("FRONTEND_ORIGIN", &origin);
        c
    }
}

/// Poll /api/health (with the bearer token) until healthy or the timeout hits.
fn wait_for_health(base: &str, token: &str, timeout: Duration) -> bool {
    let url = format!("{base}/api/health");
    let bearer = format!("Bearer {token}");
    let deadline = Instant::now() + timeout;
    while Instant::now() < deadline {
        let ok = ureq::get(&url)
            .set("Authorization", &bearer)
            .timeout(Duration::from_secs(2))
            .call()
            .map(|r| r.status() == 200)
            .unwrap_or(false);
        if ok {
            return true;
        }
        std::thread::sleep(Duration::from_millis(250));
    }
    false
}

fn main() {
    let app = tauri::Builder::default()
        .setup(|app| {
            let port = pick_free_port();
            let token = uuid::Uuid::new_v4().to_string();
            let base = format!("http://127.0.0.1:{port}");

            let child = resolve_sidecar(app, port, &token)
                .spawn()
                .expect("failed to spawn the Yunaki sidecar");
            app.manage(SidecarProcess(Mutex::new(Some(child))));

            if !wait_for_health(&base, &token, Duration::from_secs(30)) {
                eprintln!(
                    "warning: sidecar did not report healthy within 30s; the window \
                     will load but backend calls may fail until it is up"
                );
            }

            // serde_json quoting keeps the values safe to inline into JS.
            let script = format!(
                "window.__YUNAKI_API__ = {{ base: {}, token: {} }};",
                serde_json::to_string(&base).expect("serialize base"),
                serde_json::to_string(&token).expect("serialize token"),
            );

            WebviewWindowBuilder::new(app, "main", WebviewUrl::App("index.html".into()))
                .title("Yunaki")
                .inner_size(1280.0, 860.0)
                .min_inner_size(900.0, 600.0)
                .initialization_script(&script)
                .build()?;

            Ok(())
        })
        .build(tauri::generate_context!())
        .expect("error building the Yunaki desktop app");

    app.run(|app_handle, event| match event {
        RunEvent::ExitRequested { .. } | RunEvent::Exit => {
            if let Some(state) = app_handle.try_state::<SidecarProcess>() {
                if let Ok(mut guard) = state.0.lock() {
                    if let Some(mut child) = guard.take() {
                        let _ = child.kill();
                        let _ = child.wait();
                    }
                }
            }
        }
        _ => {}
    });
}
