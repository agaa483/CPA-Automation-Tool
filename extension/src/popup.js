const statusEl = document.getElementById("status");
const hintEl = document.getElementById("hint");
document.getElementById("openOptions").addEventListener("click", () => {
  chrome.runtime.openOptionsPage();
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
