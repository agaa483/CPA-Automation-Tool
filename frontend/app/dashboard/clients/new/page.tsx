"use client";
import { useState } from "react";
import { useRouter } from "next/navigation";
import { useApi } from "@/lib/api";

export default function NewClientPage() {
  const api = useApi();
  const [name, setName] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const router = useRouter();

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setErr(null);
    try {
      const c = await api.createClient(name);
      router.push(`/dashboard/clients/${c.id}`);
    } catch (e) {
      setErr(String(e));
      setBusy(false);
    }
  }

  return (
    <div className="max-w-md space-y-6">
      <h1 className="text-2xl font-semibold">Add a client</h1>
      <form onSubmit={submit} className="space-y-4">
        <label className="block">
          <span className="text-sm font-medium">Client name</span>
          <input
            className="mt-1 block w-full rounded-md border-gray-300 border p-2"
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="e.g. LEELA Foundation"
            required
          />
        </label>
        {err && <p className="text-red-600 text-sm">{err}</p>}
        <button
          type="submit"
          disabled={busy}
          className="rounded-md bg-black px-4 py-2 text-white text-sm font-medium disabled:opacity-50"
        >
          {busy ? "Creating…" : "Create client"}
        </button>
      </form>
      <p className="text-sm text-gray-500">
        After creating you'll be able to connect QuickBooks, Outlook, and configure
        receipt senders.
      </p>
    </div>
  );
}
