// Minimal, explicit bridge between the sandboxed interface and the desktop shell.
const { contextBridge, ipcRenderer, webUtils } = require("electron");

contextBridge.exposeInMainWorld("oncopixel", {
  getPathForFile: (file) => webUtils.getPathForFile(file),
  selectFolder: () => ipcRenderer.invoke("dialog:folder"),
  selectFile: (opts) => ipcRenderer.invoke("dialog:file", opts ?? {}),
  showItemInFolder: (p) => ipcRenderer.send("shell:show", String(p)),
  appVersion: ipcRenderer.sendSync("app:version"),
  platform: process.platform,
});
