// Service worker: handles HTTPS calls to the backend on behalf of the content script.
// Content scripts can't make cross-origin requests, so they message this worker instead.

const DEFAULT_BACKEND = "https://qb-auditor-backend.fly.dev";

async function getSettings() {
  const s = await chrome.storage.local.get(["token", "clientId", "backendUrl"]);
  return {
    token: s.token || "",
    clientId: s.clientId ? Number(s.clientId) : null,
    backendUrl: s.backendUrl || DEFAULT_BACKEND,
  };
}

async function categorize(txns) {
  const { token, clientId, backendUrl } = await getSettings();
  if (!token) throw new Error("No extension token configured. Open the extension Options page.");
  if (!clientId) throw new Error("No client selected. Open the extension Options page.");

  const r = await fetch(`${backendUrl}/extension/categorize`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "X-Extension-Token": token,
    },
    body: JSON.stringify({ client_id: clientId, txns }),
  });

  if (!r.ok) {
    const text = await r.text();
    throw new Error(`${r.status}: ${text}`);
  }
  return r.json();
}

// Route messages from content script.
chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  if (message.action === "categorize") {
    categorize(message.txns)
      .then((data) => sendResponse({ ok: true, data }))
      .catch((err) => sendResponse({ ok: false, error: String(err.message || err) }));
    return true; // keep the message channel open for async response
  }

  if (message.action === "getSettings") {
    getSettings()
      .then((s) => sendResponse({ ok: true, data: s }))
      .catch((err) => sendResponse({ ok: false, error: String(err.message || err) }));
    return true;
  }
});
