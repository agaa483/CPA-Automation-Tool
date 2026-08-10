"use client";
import { useState } from "react";
import Link from "next/link";
import { useApi } from "@/lib/api";

export default function ExtensionSettingsPage() {
  const api = useApi();
  const [token, setToken] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  async function generate() {
    setBusy(true);
    setErr(null);
    try {
      const r = await api.generateExtensionToken();
      setToken(r.token);
    } catch (e) {
      setErr(String(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="space-y-6 max-w-2xl">
      <div>
        <Link href="/dashboard" className="text-sm text-gray-500 hover:underline">
          ← Dashboard
        </Link>
        <h1 className="text-2xl font-semibold mt-1">Chrome extension</h1>
      </div>

      <div className="rounded-lg border bg-white p-5 space-y-3">
        <h2 className="font-semibold">Install the extension</h2>
        <ol className="list-decimal list-inside space-y-1 text-sm text-gray-700">
          <li>
            Download the extension folder from the{" "}
            <code className="bg-gray-100 px-1 py-0.5 rounded text-xs">extension/</code> directory in the GitHub repo.
          </li>
          <li>
            Open <code className="bg-gray-100 px-1 py-0.5 rounded text-xs">chrome://extensions</code>
          </li>
          <li>Enable <b>Developer mode</b> (top right toggle).</li>
          <li>Click <b>Load unpacked</b> and select the extension folder.</li>
          <li>Open the extension's Options page and paste the token below.</li>
        </ol>
      </div>

      <div className="rounded-lg border bg-white p-5 space-y-3">
        <h2 className="font-semibold">Extension token</h2>
        <p className="text-sm text-gray-600">
          Generate a token below and paste it into the extension's Options page.
          The token authenticates the extension as your account and stays valid until revoked.
        </p>

        {token ? (
          <div className="space-y-3">
            <div className="rounded-md bg-yellow-50 border border-yellow-200 p-3 text-sm">
              <b>Save this now.</b> It won't be shown again.
            </div>
            <div className="flex gap-2">
              <input
                readOnly
                value={token}
                className="flex-1 font-mono text-sm rounded-md border p-2 bg-gray-50"
              />
              <button
                onClick={() => navigator.clipboard.writeText(token)}
                className="rounded-md bg-black text-white px-4 py-2 text-sm font-medium"
              >
                Copy
              </button>
            </div>
            <button
              onClick={generate}
              disabled={busy}
              className="text-sm text-gray-500 hover:underline"
            >
              Generate another token
            </button>
          </div>
        ) : (
          <button
            onClick={generate}
            disabled={busy}
            className="rounded-md bg-black text-white px-4 py-2 text-sm font-medium disabled:opacity-50"
          >
            {busy ? "Generating…" : "Generate token"}
          </button>
        )}
        {err && <p className="text-red-600 text-sm">{err}</p>}
      </div>

      <div className="rounded-lg border bg-white p-5 space-y-3">
        <h2 className="font-semibold">How it works</h2>
        <ol className="list-decimal list-inside space-y-1 text-sm text-gray-700">
          <li>Open QuickBooks Online in the same browser.</li>
          <li>Navigate to Bookkeeping → Transactions → Bank transactions → For Review.</li>
          <li>The extension detects the page and shows AI-suggested categories inline.</li>
          <li>Review the suggestions and hit QBO's own <b>Accept</b> button per row.</li>
        </ol>
      </div>
    </div>
  );
}
