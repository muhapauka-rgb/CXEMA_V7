"use strict"

const { contextBridge, ipcRenderer } = require("electron")

contextBridge.exposeInMainWorld("cxemaDesktop", {
  runUpdate: async () => {
    return ipcRenderer.invoke("cxema:update-command")
  },
})
