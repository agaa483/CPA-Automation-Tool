"use client";
import { useEffect, useState } from "react";
import Link from "next/link";
import { useParams, useSearchParams } from "next/navigation";
import { useApi } from "@/lib/api";
import type { Client, Category } from "@/lib/types";
import { ReceiptSendersInput } from "@/components/ReceiptSendersInput";

function ConnectionRow({
  label,
  connected,
  onConnect,
}: {
  label: string;
  connected: boolean;
  onConnect: () => void | Promise<void>;
}) {
  const [busy, setBusy] = useState(false);
  return (
    <div className="flex items-center justify-between">
      <span>{label}</span>
      <div className="flex items-center gap-2">
        <span
          className={`px-2 py-1 rounded text-xs ${
            connected
              ? "bg-green-100 text-green-700"
              : "bg-gray-100 text-gray-500"
          }`}
        >
          {connected ? "Connected" : "Not connected"}
        </span>
        <button
          onClick={async () => {
            setBusy(true);
            try {
              await onConnect();
            } finally {
              setBusy(false);
            }
          }}
          disabled={busy}
          className="text-xs rounded-md border px-3 py-1 disabled:opacity-50"
        >
          {busy ? "…" : connected ? "Reconnect" : "Connect"}
        </button>
      </div>
    </div>
  );
}

export default function ClientPage() {
  const api = useApi();
  const params = useParams();
  const search = useSearchParams();
  const id = Number(params.id);
  const [client, setClient] = useState<Client | null>(null);
  const [cats, setCats] = useState<Category[] | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [syncing, setSyncing] = useState(false);

  const qboOk = search.get("qbo_connected");
  const qboErr = search.get("qbo_error");
  const outlookOk = search.get("outlook_connected");
  const outlookErr = search.get("outlook_error");

  useEffect(() => {
    api.getClient(id).then(setClient).catch((e) => setErr(String(e)));
    api.listCategories(id).then(setCats).catch(() => setCats([]));
  }, [api, id]);

  async function syncCats() {
    setSyncing(true);
    try {
      await api.syncCategories(id);
      const fresh = await api.listCategories(id);
      setCats(fresh);
    } catch (e) {
      setErr(String(e));
    } finally {
      setSyncing(false);
    }
  }

  if (err) return <p className="text-red-600">Error: {err}</p>;
  if (!client) return <p>Loading…</p>;

  return (
    <div className="space-y-8">
      <div>
        <Link href="/dashboard" className="text-sm text-gray-500 hover:underline">
          ← All clients
        </Link>
        <h1 className="text-2xl font-semibold mt-1">{client.firm_name}</h1>
      </div>

      {(qboOk || outlookOk) && (
        <div className="rounded-md bg-green-50 border border-green-200 text-green-800 px-4 py-2 text-sm">
          {qboOk && "QuickBooks connected. "}
          {outlookOk && "Outlook connected. "}
        </div>
      )}
      {(qboErr || outlookErr) && (
        <div className="rounded-md bg-red-50 border border-red-200 text-red-800 px-4 py-2 text-sm">
          {qboErr && `QBO error: ${qboErr}. `}
          {outlookErr && `Outlook error: ${outlookErr}.`}
        </div>
      )}

      <div className="flex gap-3">
        <Link
          href={`/dashboard/clients/${id}/audit`}
          className="rounded-md bg-black px-4 py-2 text-white text-sm font-medium"
        >
          Run audit
        </Link>
        <Link
          href={`/dashboard/clients/${id}/excel`}
          className="rounded-md border border-black px-4 py-2 text-sm font-medium"
        >
          Audit spreadsheet
        </Link>
      </div>

      <section className="rounded-lg border bg-white p-5 space-y-3">
        <h2 className="font-semibold">Connections</h2>
        <div className="flex flex-col gap-3 text-sm">
          <ConnectionRow
            label="QuickBooks Online"
            connected={client.qbo_connected}
            onConnect={async () => {
              const { auth_url } = await api.qboAuthUrl(id);
              window.location.href = auth_url;
            }}
          />
          <ConnectionRow
            label="Outlook"
            connected={client.outlook_connected}
            onConnect={async () => {
              const { auth_url } = await api.outlookAuthUrl(id);
              window.location.href = auth_url;
            }}
          />
        </div>
      </section>

      <section className="rounded-lg border bg-white p-5 space-y-3">
        <div className="flex items-center justify-between">
          <h2 className="font-semibold">Receipt senders</h2>
        </div>
        <p className="text-xs text-gray-500">
          Email addresses that forward this client's receipts to your inbox.
          We only pull emails from these senders during audits.
        </p>
        <ReceiptSendersInput clientId={id} />
      </section>

      <section className="rounded-lg border bg-white p-5 space-y-3">
        <div className="flex items-center justify-between">
          <h2 className="font-semibold">Chart of accounts</h2>
          <button
            onClick={syncCats}
            disabled={syncing}
            className="text-sm rounded-md border px-3 py-1 disabled:opacity-50"
          >
            {syncing ? "Syncing…" : "Sync from QBO"}
          </button>
        </div>
        {cats == null ? (
          <p className="text-sm text-gray-500">Loading…</p>
        ) : cats.length === 0 ? (
          <p className="text-sm text-gray-500">
            No categories yet. Click <b>Sync from QBO</b> once connected.
          </p>
        ) : (
          <details className="text-sm">
            <summary className="cursor-pointer text-gray-700">
              {cats.length} accounts
            </summary>
            <ul className="mt-2 space-y-1 max-h-64 overflow-auto">
              {cats.map((c) => (
                <li key={c.id} className="text-gray-600 text-xs">
                  {c.name}
                </li>
              ))}
            </ul>
          </details>
        )}
      </section>
    </div>
  );
}
