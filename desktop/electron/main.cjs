// OncoPixel desktop shell: starts the local Python backend, then shows the interface.
// Nothing here talks to the network except 127.0.0.1.
const { app, BrowserWindow, dialog, ipcMain, shell, session, Menu } = require("electron");
const { spawn } = require("node:child_process");
const crypto = require("node:crypto");
const fs = require("node:fs");
const path = require("node:path");

const PACKAGED = app.isPackaged;
const ROOT = PACKAGED ? process.resourcesPath : path.resolve(__dirname, "..", "..");
const BACKEND_DIR = path.join(ROOT, "backend");
const FRONTEND_DIR = PACKAGED ? path.join(process.resourcesPath, "dist") : path.resolve(__dirname, "..", "dist");
const TOKEN = crypto.randomBytes(32).toString("hex");
const START_TIMEOUT_MS = 90_000;

let backend = null;
let win = null;
let port = null;
let quitting = false;

function findPython() {
  const candidates = [
    process.env.ONCOPIXEL_PYTHON,
    path.join(BACKEND_DIR, ".venv", "bin", "python"),
    path.join(ROOT, ".venv", "bin", "python"),
    path.join(app.getPath("userData"), "venv", "bin", "python"),
    path.join(BACKEND_DIR, ".venv", "Scripts", "python.exe"),
  ].filter(Boolean);
  for (const c of candidates) if (fs.existsSync(c)) return c;
  return process.platform === "win32" ? "python" : "python3";
}

function modelsDir() {
  // A packaged app keeps weights beside its data, never inside the bundle.
  if (process.env.ONCOPIXEL_MODELS_DIR) return process.env.ONCOPIXEL_MODELS_DIR;
  return PACKAGED ? path.join(app.getPath("userData"), "models") : path.join(ROOT, "models");
}

function startBackend() {
  return new Promise((resolve, reject) => {
    const py = findPython();
    const env = {
      ...process.env,
      ONCOPIXEL_APP_TOKEN: TOKEN,
      ONCOPIXEL_MODELS_DIR: modelsDir(),
      ONCOPIXEL_FRONTEND_DIR: FRONTEND_DIR,
      PYTORCH_ENABLE_MPS_FALLBACK: "1",
      PYTHONUNBUFFERED: "1",
    };
    fs.mkdirSync(env.ONCOPIXEL_MODELS_DIR, { recursive: true });
    let log = "";
    backend = spawn(py, ["-m", "oncopixel.server"], { cwd: BACKEND_DIR, env, stdio: ["ignore", "pipe", "pipe"] });
    const timer = setTimeout(() => reject(new Error(`The backend did not start within ${START_TIMEOUT_MS / 1000} s.\n${log.slice(-1500)}`)), START_TIMEOUT_MS);
    backend.stdout.on("data", (d) => {
      const s = d.toString();
      log += s;
      const m = s.match(/ONCOPIXEL_READY (\d+)/);
      if (m) { clearTimeout(timer); resolve(Number(m[1])); }
    });
    backend.stderr.on("data", (d) => { log += d.toString(); });
    backend.on("error", (e) => { clearTimeout(timer); reject(new Error(`Could not start Python (${py}): ${e.message}`)); });
    backend.on("exit", (code) => {
      clearTimeout(timer);
      backend = null;
      if (!quitting) reject(new Error(`The backend stopped (exit code ${code}).\n${log.slice(-1500)}`));
    });
  });
}

function stopBackend() {
  if (backend) { try { backend.kill("SIGTERM"); } catch { /* already gone */ } }
}

function fail(err) {
  dialog.showErrorBox("OncoPixel could not start", String(err && err.message ? err.message : err) +
    "\n\nSee the README, section Troubleshooting (Python environment and dependencies).");
  quitting = true;
  stopBackend();
  app.quit();
}

function createWindow() {
  const origin = `http://127.0.0.1:${port}`;
  // Attach the per-launch token to every request this app makes to its own backend.
  session.defaultSession.webRequest.onBeforeSendHeaders({ urls: [`${origin}/*`] }, (details, cb) => {
    details.requestHeaders["X-OncoPixel-App"] = TOKEN;
    cb({ requestHeaders: details.requestHeaders });
  });
  // Block anything that is not the local backend.
  session.defaultSession.webRequest.onBeforeRequest({ urls: ["http://*/*", "https://*/*", "ws://*/*", "wss://*/*"] }, (details, cb) => {
    cb({ cancel: !details.url.startsWith(origin + "/") });
  });
  session.defaultSession.setPermissionRequestHandler((_wc, _perm, cb) => cb(false));

  win = new BrowserWindow({
    width: 1440, height: 900, minWidth: 1280, minHeight: 720,
    backgroundColor: "#0b1417",
    title: "OncoPixel",
    icon: path.join(__dirname, "..", "build", "icon.png"),
    show: false,
    webPreferences: {
      preload: path.join(__dirname, "preload.cjs"),
      contextIsolation: true, nodeIntegration: false, sandbox: false, webSecurity: true,
    },
  });
  win.once("ready-to-show", () => win.show());
  win.webContents.setWindowOpenHandler(() => ({ action: "deny" }));
  win.webContents.on("will-navigate", (e, url) => { if (!url.startsWith(origin)) e.preventDefault(); });
  win.loadURL(origin);
  win.on("closed", () => { win = null; });
}

ipcMain.on("app:version", (e) => { e.returnValue = app.getVersion(); });
ipcMain.on("shell:show", (_e, p) => { if (typeof p === "string" && path.isAbsolute(p)) shell.showItemInFolder(p); });
ipcMain.handle("dialog:folder", async () => {
  const r = await dialog.showOpenDialog(win, { properties: ["openDirectory", "createDirectory"] });
  return r.canceled ? null : r.filePaths[0];
});
ipcMain.handle("dialog:file", async (_e, opts) => {
  const filters = Array.isArray(opts.filters) ? opts.filters : [];
  const r = await dialog.showOpenDialog(win, { properties: ["openFile"], filters });
  return r.canceled ? null : r.filePaths[0];
});

const lock = app.requestSingleInstanceLock();
if (!lock) app.quit();
else {
  app.on("second-instance", () => { if (win) { if (win.isMinimized()) win.restore(); win.focus(); } });
  app.whenReady().then(async () => {
    Menu.setApplicationMenu(Menu.buildFromTemplate([
      { role: "appMenu" }, { role: "editMenu" }, { role: "viewMenu" }, { role: "windowMenu" },
    ]));
    try { port = await startBackend(); } catch (e) { return fail(e); }
    createWindow();
    // Saved exports go through the normal download flow.
    session.defaultSession.on("will-download", (_e, item) => {
      item.once("done", (_ev, state) => { if (state === "completed") shell.showItemInFolder(item.getSavePath()); });
    });
  });
  app.on("window-all-closed", () => app.quit());
  app.on("before-quit", () => { quitting = true; stopBackend(); });
  process.on("exit", stopBackend);
}
