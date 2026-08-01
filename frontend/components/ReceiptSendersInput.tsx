"use client";
import { useEffect, useState } from "react";
import { useApi } from "@/lib/api";
import type { ReceiptSender } from "@/lib/types";

export function ReceiptSendersInput({ clientId }: { clientId: number }) {
  const api = useApi();
  const [senders, setSenders] = useState<ReceiptSender[]>([]);
  const [input, setInput] = useState("");
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    api.listSenders(clientId).then(setSenders).catch((e) => setErr(String(e)));
  }, [api, clientId]);

  async function add() {
    if (!input.trim()) return;
    try {
      const s = await api.addSender(clientId, input.trim());
      setSenders((cur) => [...cur.filter((x) => x.address !== s.address), s]);
      setInput("");
    } catch (e) {
      setErr(String(e));
    }
  }

  async function remove(addr: string) {
    try {
      await api.removeSender(clientId, addr);
      setSenders((cur) => cur.filter((s) => s.address !== addr));
    } catch (e) {
      setErr(String(e));
    }
  }

  return (
    <div className="space-y-3">
      <div className="flex gap-2">
        <input
          type="email"
          className="flex-1 rounded-md border p-2 text-sm"
          placeholder="receipts@example.com"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && (e.preventDefault(), add())}
        />
        <button
          onClick={add}
          className="rounded-md bg-black px-4 py-2 text-white text-sm"
        >
          Add
        </button>
      </div>
      {err && <p className="text-red-600 text-sm">{err}</p>}
      {senders.length === 0 ? (
        <p className="text-sm text-gray-500 italic">
          No receipt senders yet. Add the addresses that forward this client's
          receipts.
        </p>
      ) : (
        <ul className="space-y-1">
          {senders.map((s) => (
            <li
              key={s.address}
              className="flex items-center justify-between rounded bg-gray-100 px-3 py-2 text-sm"
            >
              <span>{s.address}</span>
              <button
                onClick={() => remove(s.address)}
                className="text-red-600 hover:underline text-xs"
              >
                remove
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
