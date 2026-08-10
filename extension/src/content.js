// Content script: injected into QBO pages. Reads the For Review table rows,
// sends txn data to the backend via the background worker, and injects
// suggestion badges next to each row.
//
// NOTE: QBO's DOM structure is not officially documented and changes over time.
// The selectors below are best-effort guesses based on common QBO patterns.
// You WILL need to inspect the actual page and update them after loading the
// extension for the first time. Look for the elements in DevTools → Elements,
// right-click → Copy → Copy selector, and update BELOW.

const SELECTORS = {
  // Data rows only (exclude the header row).
  forReviewRow: 'tr.idsTable__row:not(.idsTable__headerRow)',
  // Column cells (matched from header inspection).
  vendor: 'td.payee',
  spent: 'td.spent',
  received: 'td.received',
  date: 'td.txnDate',
  description: 'td.description',
  categoryCell: 'td.category',
};

const BADGE_CLASS = "qba-suggestion-badge";
const DEBOUNCE_MS = 800;

// Cache: content-key → suggestion. In-memory + persisted to chrome.storage.local
// so it survives page refresh.
const suggestionCache = new Map();
const inFlight = new Set();
let debounceTimer = null;
const CACHE_KEY = "qba_suggestion_cache_v1";

function contentKey(rowData) {
  return [
    rowData.date || "",
    rowData.amount.toFixed(2),
    (rowData.vendor || "").trim(),
    (rowData.description || "").trim(),
  ].join("|");
}

async function loadCacheFromStorage() {
  try {
    const stored = await chrome.storage.local.get(CACHE_KEY);
    const obj = stored[CACHE_KEY] || {};
    Object.entries(obj).forEach(([k, v]) => suggestionCache.set(k, v));
    log(`Loaded ${suggestionCache.size} cached suggestions from storage`);
  } catch (e) {
    log("Cache load failed:", e);
  }
}

let saveTimer = null;
function schedulePersist() {
  clearTimeout(saveTimer);
  saveTimer = setTimeout(async () => {
    const obj = Object.fromEntries(suggestionCache);
    try {
      await chrome.storage.local.set({ [CACHE_KEY]: obj });
    } catch (e) {
      log("Cache persist failed:", e);
    }
  }, 1000);
}

function log(...args) {
  console.log("[QB Auditor]", ...args);
}

function isForReviewPage() {
  return /banking|banktxns|bank-transactions/i.test(location.pathname);
}

function extractRowData(rowEl) {
  // Stable ID per row — cache on the element so repeated calls return the same value.
  let domId = rowEl.dataset.qbaId;
  if (!domId) {
    domId = rowEl.getAttribute("data-testid") ||
            rowEl.id ||
            "qba-row-" + Math.random().toString(36).slice(2, 10);
    rowEl.dataset.qbaId = domId;
  }

  const readText = (selectorList) => {
    for (const sel of selectorList.split(",")) {
      const el = rowEl.querySelector(sel.trim());
      if (el && el.textContent) return el.textContent.trim();
    }
    return null;
  };

  const spentText = readText(SELECTORS.spent);
  const receivedText = readText(SELECTORS.received);
  const parseAmount = (t) => {
    if (!t) return 0;
    const cleaned = t.replace(/[$,]/g, "").replace(/[()]/g, "-");
    const parsed = parseFloat(cleaned);
    return isNaN(parsed) ? 0 : parsed;
  };
  const spent = parseAmount(spentText);
  const received = parseAmount(receivedText);
  // Expenses are negative amounts. Income is positive.
  const amount = spent > 0 ? -spent : received;

  return {
    dom_id: domId,
    vendor: readText(SELECTORS.vendor),
    amount,
    date: readText(SELECTORS.date),
    description: readText(SELECTORS.description),
    current_category: readText(SELECTORS.categoryCell),
  };
}

function injectBadge(rowEl, suggestion) {
  // Remove any prior badge on this row
  rowEl.querySelectorAll("." + BADGE_CLASS).forEach((el) => el.remove());

  const badge = document.createElement("div");
  badge.className = BADGE_CLASS;

  if (suggestion.error) {
    badge.classList.add("qba-error");
    badge.textContent = `AI error: ${suggestion.error.slice(0, 100)}`;
  } else if (!suggestion.suggested_category) {
    badge.classList.add("qba-unknown");
    badge.textContent = "AI: no confident suggestion";
    badge.title = suggestion.reasoning || "";
  } else {
    badge.classList.add(`qba-${suggestion.confidence}`);
    const label = document.createElement("span");
    label.className = "qba-label";
    label.textContent = "AI suggests:";
    const cat = document.createElement("b");
    cat.textContent = suggestion.suggested_category;
    badge.appendChild(label);
    badge.appendChild(cat);
    if (suggestion.reasoning) {
      badge.title = suggestion.reasoning;
    }
    if (suggestion.suggested_payee) {
      const payee = document.createElement("small");
      payee.textContent = `  (payee: ${suggestion.suggested_payee})`;
      badge.appendChild(payee);
    }
  }

  // Inject at the top of the row's category cell, or fall back to prepending on the row.
  const catCell = rowEl.querySelector(SELECTORS.categoryCell);
  if (catCell) {
    catCell.prepend(badge);
  } else {
    rowEl.prepend(badge);
  }
}

const BATCH_SIZE = 5;

function rowNeedsBadge(rowEl) {
  return !rowEl.querySelector("." + BADGE_CLASS);
}

async function processRows() {
  if (!isForReviewPage()) return;

  const rows = Array.from(document.querySelectorAll(SELECTORS.forReviewRow));
  if (rows.length === 0) return;

  // 1) For rows that already have a cached suggestion but no badge → inject.
  let restored = 0;
  const toFetch = [];
  for (const row of rows) {
    if (!rowNeedsBadge(row)) continue;
    const rowData = extractRowData(row);
    const key = contentKey(rowData);
    const cached = suggestionCache.get(key);
    if (cached) {
      injectBadge(row, cached);
      restored++;
    } else if (!inFlight.has(key)) {
      inFlight.add(key);
      toFetch.push({ row, rowData, key });
    }
  }
  if (restored > 0) log(`Restored ${restored} cached badges`);
  if (toFetch.length === 0) return;

  log(`Fetching suggestions for ${toFetch.length} new rows (batches of ${BATCH_SIZE})`);

  for (let i = 0; i < toFetch.length; i += BATCH_SIZE) {
    const batch = toFetch.slice(i, i + BATCH_SIZE);
    const txns = batch.map((b) => b.rowData);
    log(`  Batch ${i / BATCH_SIZE + 1}: sending ${txns.length} txns…`);

    chrome.runtime.sendMessage({ action: "categorize", txns }, (response) => {
      if (!response) {
        log("  No response from background worker");
        batch.forEach((b) => inFlight.delete(b.key));
        return;
      }
      if (!response.ok) {
        log("  Categorize error:", response.error);
        batch.forEach((b) => inFlight.delete(b.key));
        return;
      }
      const suggestions = response.data.suggestions || [];
      const byId = new Map(suggestions.map((s) => [s.dom_id, s]));
      let injected = 0;
      // Cache everything first so navigation-back restores from cache.
      batch.forEach((b) => {
        const sug = byId.get(b.rowData.dom_id);
        if (sug) suggestionCache.set(b.key, sug);
        inFlight.delete(b.key);
      });
      schedulePersist();
      // Then find matching rows in the CURRENT DOM (may have been re-rendered)
      // and inject. This handles the case where pagination happened during fetch.
      const currentRows = document.querySelectorAll(SELECTORS.forReviewRow);
      currentRows.forEach((row) => {
        if (!rowNeedsBadge(row)) return;
        const rowData = extractRowData(row);
        const cached = suggestionCache.get(contentKey(rowData));
        if (cached) {
          injectBadge(row, cached);
          injected++;
        }
      });
      log(`  Batch done: ${injected} badges injected (in current DOM)`);
    });
  }
}

function scheduleProcess() {
  clearTimeout(debounceTimer);
  debounceTimer = setTimeout(processRows, DEBOUNCE_MS);
}

// Watch for DOM changes (QBO is a SPA — rows appear async as user scrolls / navigates).
const observer = new MutationObserver(() => scheduleProcess());
observer.observe(document.body, { childList: true, subtree: true });

// Load persisted cache first, then start processing.
loadCacheFromStorage().then(() => scheduleProcess());

log("QB Auditor extension loaded");
