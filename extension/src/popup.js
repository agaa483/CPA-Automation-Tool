const statusEl = document.getElementById("status");
const hintEl = document.getElementById("hint");

document.getElementById("openOptions").addEventListener("click", () => {
  chrome.runtime.openOptionsPage();
});

document.getElementById("refresh").addEventListener("click", async () => {
  statusEl.className = "status";
  statusEl.textContent = "Clearing cache…";

  const s = await chrome.storage.local.get(["token", "clientId", "backendUrl"]);
  if (!s.token || !s.clientId) {
    statusEl.className = "status bad";
    statusEl.textContent = "Set up token + client first.";
    return;
  }
  const backendUrl = (s.backendUrl || "https://qb-auditor-backend.fly.dev").replace(/\/$/, "");

  try {
    // 1) Clear server cache for this client
    const r = await fetch(`${backendUrl}/extension/clear-cache?client_id=${s.clientId}`, {
      method: "POST",
      headers: { "X-Extension-Token": s.token },
    });
    if (!r.ok) throw new Error(`${r.status}: ${await r.text()}`);
    const { deleted } = await r.json();

    // 2) Clear local extension cache too
    await chrome.storage.local.remove("qba_suggestion_cache_v1");

    // 3) Tell the QBO tab to re-fetch
    const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
    if (tab && tab.id) {
      chrome.tabs.sendMessage(tab.id, { action: "refetch" }).catch(() => {});
      chrome.tabs.reload(tab.id);
    }

    statusEl.className = "status ok";
    statusEl.textContent = `Cleared ${deleted} cached · page reloading`;
  } catch (e) {
    statusEl.className = "status bad";
    statusEl.textContent = `Error: ${e.message || e}`;
  }
});

chrome.runtime.sendMessage({ action: "getSettings" }, (response) => {
  if (!response || !response.ok) {
    statusEl.className = "status bad";
    statusEl.textContent = "Extension error";
    return;
  }
  const { token, clientId } = response.data;
  if (!token) {
    statusEl.className = "status bad";
    statusEl.textContent = "No token";
    hintEl.textContent = "Paste an extension token in settings.";
  } else if (!clientId) {
    statusEl.className = "status bad";
    statusEl.textContent = "No client selected";
    hintEl.textContent = "Choose a client in settings.";
  } else {
    statusEl.className = "status ok";
    statusEl.textContent = `Connected · client ${clientId}`;
    hintEl.textContent = "Open QBO Bank Transactions to see suggestions.";
  }
});
