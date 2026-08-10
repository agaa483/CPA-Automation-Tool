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

let seenRows = new WeakSet();
let debounceTimer = null;

function log(...args) {
  console.log("[QB Auditor]", ...args);
}

function isForReviewPage() {
  return /banking|banktxns|bank-transactions/i.test(location.pathname);
}

function extractRowData(rowEl) {
  const domId = rowEl.getAttribute("data-testid") ||
                rowEl.id ||
                "row-" + Math.random().toString(36).slice(2, 10);

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

async function processRows() {
  if (!isForReviewPage()) return;

  const rows = document.querySelectorAll(SELECTORS.forReviewRow);
  const newRows = Array.from(rows).filter((r) => !seenRows.has(r));
  if (newRows.length === 0) return;

  log(`Processing ${newRows.length} new rows`);

  const txns = newRows.map(extractRowData);
  newRows.forEach((r) => seenRows.add(r));

  chrome.runtime.sendMessage(
    { action: "categorize", txns },
    (response) => {
      if (!response) {
        log("No response from background worker (extension might need reload)");
        return;
      }
      if (!response.ok) {
        log("Categorize error:", response.error);
        return;
      }
      const suggestions = response.data.suggestions || [];
      const byId = new Map(suggestions.map((s) => [s.dom_id, s]));
      newRows.forEach((row) => {
        const rowData = extractRowData(row);
        const sug = byId.get(rowData.dom_id);
        if (sug) injectBadge(row, sug);
      });
    }
  );
}

function scheduleProcess() {
  clearTimeout(debounceTimer);
  debounceTimer = setTimeout(processRows, DEBOUNCE_MS);
}

// Watch for DOM changes (QBO is a SPA — rows appear async as user scrolls / navigates).
const observer = new MutationObserver(() => scheduleProcess());
observer.observe(document.body, { childList: true, subtree: true });

// Initial run
scheduleProcess();

log("QB Auditor extension loaded");
