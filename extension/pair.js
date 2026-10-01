// Runs only on the job-bot site. Lets the site hand this extension its key
// when you click "Connect browser extension" in Settings.
const reply = (msg) => window.postMessage({ source: "jobbot-ext", ...msg }, location.origin);

window.addEventListener("message", async (e) => {
  if (e.source !== window || e.origin !== location.origin) return;
  const d = e.data || {};
  if (d.source !== "jobbot-page") return;
  if (d.type === "ping") {
    const { token } = await chrome.storage.local.get("token");
    reply({ type: "pong", connected: !!token });
  } else if (d.type === "connect" && typeof d.token === "string" && d.token.startsWith("jbx_")) {
    await chrome.storage.local.set({ token: d.token, api: location.origin });
    reply({ type: "connected" });
  } else if (d.type === "disconnect") {
    await chrome.storage.local.remove("token");
    reply({ type: "disconnected" });
  }
});
reply({ type: "present" });
