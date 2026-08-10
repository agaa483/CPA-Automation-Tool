# QB Auditor — Chrome Extension

Injects AI-suggested categories into QuickBooks Online's Bank Transactions →
For Review page. Runs alongside your normal QBO session.

## Install (development mode)

1. Open `chrome://extensions` in Chrome.
2. Toggle **Developer mode** on (top-right).
3. Click **Load unpacked** → select this `extension/` folder.
4. The extension icon should appear in your toolbar.
5. Right-click the icon → **Options** → paste your extension token from the web app dashboard and set the Client ID.
6. Open QBO. Navigate to **Bookkeeping → Transactions → Bank transactions → For Review**.
7. You'll see AI-suggested categories appear next to each row.

## Getting an extension token

1. Sign in to the web app.
2. Go to **Dashboard → Settings → Chrome extension** (`/dashboard/settings/extension`).
3. Click **Generate token**. Copy the value.
4. Paste into the extension's Options page.

## Files

- `manifest.json` — Chrome extension config
- `src/background.js` — service worker, handles HTTPS to backend
- `src/content.js` — runs on QBO pages, reads DOM + injects suggestions
- `src/popup.html` + `popup.js` — extension icon popup
- `src/options.html` + `options.js` — settings page
- `src/style.css` — badge styling
- `icons/` — extension icons

## Icons

Placeholder — replace `icons/icon-16.png`, `icons/icon-48.png`, `icons/icon-128.png` with real assets before publishing to the Chrome Web Store.

## Selector maintenance

QBO's UI changes occasionally. The DOM selectors in `src/content.js` under `SELECTORS` will need adjustment when Intuit ships redesigns. To debug:

1. Load extension in Chrome dev mode.
2. Open QBO's For Review page.
3. Open DevTools → Console. Look for `[QB Auditor]` log lines.
4. If no rows are detected, right-click a real transaction row → **Inspect** → find its class name → update the corresponding entry in `SELECTORS`.
5. Reload the extension (`chrome://extensions` → reload icon), refresh QBO page.

## Publishing

Once selectors are stable and icons are ready:

1. Chrome Web Store dev account ($5 one-time fee) at https://chrome.google.com/webstore/devconsole
2. Zip the `extension/` folder
3. Upload via developer dashboard
4. Fill in description, screenshots, category (Productivity)
5. Submit for review (~1 week)
