const DEFAULT_BACKEND = "https://qb-auditor-backend.fly.dev";

const backendEl = document.getElementById("backendUrl");
const tokenEl = document.getElementById("token");
const clientSelectEl = document.getElementById("clientSelect");
const statusEl = document.getElementById("status");

async function load() {
  const s = await chrome.storage.local.get(["token", "clientId", "backendUrl"]);
  backendEl.value = s.backendUrl || DEFAULT_BACKEND;
  tokenEl.value = s.token || "";

  // If we already have a token, auto-load clients on open.
  if (s.token) {
    await loadClients(s.clientId);
  }
}

async function loadClients(preselectId) {
  const token = tokenEl.value.trim();
  const backendUrl = (backendEl.value.trim() || DEFAULT_BACKEND).replace(/\/$/, "");
  if (!token) {
    show("Enter a token first.", false);
    return;
  }
  clientSelectEl.disabled = true;
  clientSelectEl.innerHTML = '<option value="">Loading…</option>';

  try {
    const r = await fetch(`${backendUrl}/extension/clients`, {
      headers: { "X-Extension-Token": token },
    });
    if (!r.ok) throw new Error(`${r.status}: ${await r.text()}`);
    const clients = await r.json();

    if (clients.length === 0) {
      clientSelectEl.innerHTML =
        '<option value="">No clients in this firm — create one in the web app first</option>';
      show("Token valid but this firm has no clients yet.", false);
      return;
    }

    clientSelectEl.innerHTML = clients
      .map(
        (c) =>
          `<option value="${c.id}" ${
            c.id === preselectId ? "selected" : ""
          }>${c.firm_name} (id ${c.id})</option>`
      )
      .join("");
    clientSelectEl.disabled = false;
    show(`Loaded ${clients.length} client(s).`, true);
  } catch (e) {
    clientSelectEl.innerHTML = '<option value="">— Load failed —</option>';
    show(`Failed to load clients: ${e.message || e}`, false);
  }
}

document.getElementById("loadClients").addEventListener("click", () => loadClients());

document.getElementById("save").addEventListener("click", async () => {
  const token = tokenEl.value.trim();
  const clientId = clientSelectEl.value;
  const backendUrl = backendEl.value.trim() || DEFAULT_BACKEND;

  if (!token) {
    show("Token is required.", false);
    return;
  }
  if (!clientId) {
    show("Pick a client from the dropdown.", false);
    return;
  }

  await chrome.storage.local.set({
    token,
    clientId: Number(clientId),
    backendUrl,
  });

  show("Saved. Refresh QBO's For Review page to see suggestions.", true);
});

function show(msg, ok) {
  statusEl.style.display = "block";
  statusEl.textContent = msg;
  statusEl.className = "status " + (ok ? "ok" : "bad");
}

load();
