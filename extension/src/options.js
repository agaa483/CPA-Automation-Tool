const DEFAULT_BACKEND = "https://qb-auditor-backend.fly.dev";

const backendEl = document.getElementById("backendUrl");
const tokenEl = document.getElementById("token");
const clientIdEl = document.getElementById("clientId");
const statusEl = document.getElementById("status");

async function load() {
  const s = await chrome.storage.local.get(["token", "clientId", "backendUrl"]);
  backendEl.value = s.backendUrl || DEFAULT_BACKEND;
  tokenEl.value = s.token || "";
  clientIdEl.value = s.clientId || "";
}

document.getElementById("save").addEventListener("click", async () => {
  const token = tokenEl.value.trim();
  const clientId = clientIdEl.value.trim();
  const backendUrl = backendEl.value.trim() || DEFAULT_BACKEND;

  if (!token) {
    show("Token is required.", false);
    return;
  }
  if (!clientId || isNaN(Number(clientId))) {
    show("Client ID must be a number.", false);
    return;
  }

  await chrome.storage.local.set({
    token,
    clientId: Number(clientId),
    backendUrl,
  });

  show("Saved. Open QBO Bank Transactions to see suggestions.", true);
});

function show(msg, ok) {
  statusEl.style.display = "block";
  statusEl.textContent = msg;
  statusEl.className = "status " + (ok ? "ok" : "bad");
}

load();
