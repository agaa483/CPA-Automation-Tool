"use client";
import { useEffect, useState } from "react";
import Link from "next/link";
import { useApi } from "@/lib/api";
import type { Client } from "@/lib/types";

export default function Dashboard() {
  const api = useApi();
  const [clients, setClients] = useState<Client[] | null>(null);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    api.listClients().then(setClients).catch((e) => setErr(String(e)));
  }, [api]);

  if (err) return <p className="text-red-600">Error: {err}</p>;
  if (!clients) return <p>Loading…</p>;

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-semibold">Clients</h1>
        <Link
          href="/dashboard/clients/new"
          className="rounded-md bg-black px-4 py-2 text-white text-sm font-medium"
        >
          + Add client
        </Link>
      </div>

      {clients.length === 0 ? (
        <div className="rounded-lg border-2 border-dashed p-12 text-center text-gray-500">
          No clients yet. Click <b>Add client</b> to onboard your first one.
        </div>
      ) : (
        <div className="grid gap-4 sm:grid-cols-2">
          {clients.map((c) => (
            <Link
              key={c.id}
              href={`/dashboard/clients/${c.id}`}
              className="rounded-lg border bg-white p-5 hover:shadow-md transition"
            >
              <div className="font-semibold text-lg">{c.firm_name}</div>
              <div className="mt-3 flex gap-2 text-xs">
                <span
                  className={`px-2 py-1 rounded ${
                    c.qbo_connected
                      ? "bg-green-100 text-green-700"
                      : "bg-gray-100 text-gray-500"
                  }`}
                >
                  QBO {c.qbo_connected ? "✓" : "not connected"}
                </span>
                <span
                  className={`px-2 py-1 rounded ${
                    c.outlook_connected
                      ? "bg-green-100 text-green-700"
                      : "bg-gray-100 text-gray-500"
                  }`}
                >
                  Outlook {c.outlook_connected ? "✓" : "not connected"}
                </span>
              </div>
            </Link>
          ))}
        </div>
      )}
    </div>
  );
}
