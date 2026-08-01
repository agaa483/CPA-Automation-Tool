"use client";
import { useState } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useApi } from "@/lib/api";
import type { AuditRunResult, FlaggedTxn } from "@/lib/types";

export default function AuditPage() {
  const api = useApi();
  const params = useParams();
  const id = Number(params.id);

  const [result, setResult] = useState<AuditRunResult | null>(null);
  const [running, setRunning] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [selected, setSelected] = useState<Set<number>>(new Set());
  const [applying, setApplying] = useState(false);
  const [applyMsg, setApplyMsg] = useState<string | null>(null);

  async function run() {
    setRunning(true);
    setErr(null);
    setResult(null);
    setSelected(new Set());
    try {
      const r = await api.runAudit(id);
      setResult(r);
      // Pre-select all flagged rows
      setSelected(new Set(r.flagged_details.map((f) => f.txn_db_id)));
    } catch (e) {
      setErr(String(e));
    } finally {
      setRunning(false);
    }
  }

  async function apply() {
    if (selected.size === 0) return;
    setApplying(true);
    setApplyMsg(null);
    try {
      const r = await api.applyCorrections(id, Array.from(selected));
      setApplyMsg(`Applied ${r.applied}, failed ${r.failed}`);
    } catch (e) {
      setApplyMsg(`Error: ${String(e)}`);
    } finally {
      setApplying(false);
    }
  }

  function toggle(txnId: number) {
    setSelected((cur) => {
      const next = new Set(cur);
      if (next.has(txnId)) next.delete(txnId);
      else next.add(txnId);
      return next;
    });
  }

  return (
    <div className="space-y-6">
      <div>
        <Link
          href={`/dashboard/clients/${id}`}
          className="text-sm text-gray-500 hover:underline"
        >
          ← Client
        </Link>
        <h1 className="text-2xl font-semibold mt-1">Run audit</h1>
      </div>

      <div className="flex gap-3 items-center">
        <button
          onClick={run}
          disabled={running}
          className="rounded-md bg-black px-4 py-2 text-white text-sm font-medium disabled:opacity-50"
        >
          {running ? "Auditing… (can take a few minutes)" : "Run audit"}
        </button>
        {result && (
          <button
            onClick={apply}
            disabled={applying || selected.size === 0}
            className="rounded-md bg-green-600 px-4 py-2 text-white text-sm font-medium disabled:opacity-50"
          >
            {applying ? "Applying…" : `Apply ${selected.size} correction(s)`}
          </button>
        )}
      </div>
      {err && <p className="text-red-600 text-sm">{err}</p>}
      {applyMsg && <p className="text-sm">{applyMsg}</p>}

      {result && (
        <>
          <div className="grid grid-cols-4 gap-3 text-sm">
            <Stat label="Audited" value={result.audited} />
            <Stat label="No change" value={result.no_change} color="green" />
            <Stat label="Flagged" value={result.flagged} color="yellow" />
            <Stat label="Errors" value={result.errors} color="red" />
          </div>

          {result.flagged_details.length === 0 ? (
            <p className="text-gray-500 text-sm">Nothing flagged 🎉</p>
          ) : (
            <div className="rounded-lg border bg-white overflow-x-auto">
              <table className="w-full text-sm">
                <thead className="bg-gray-50 text-left">
                  <tr>
                    <th className="p-2 w-8"></th>
                    <th className="p-2">Date</th>
                    <th className="p-2">Vendor</th>
                    <th className="p-2 text-right">Amount</th>
                    <th className="p-2">Current</th>
                    <th className="p-2">Suggested</th>
                    <th className="p-2">Reasoning</th>
                  </tr>
                </thead>
                <tbody>
                  {result.flagged_details.map((f) => (
                    <FlagRow
                      key={f.txn_db_id}
                      f={f}
                      checked={selected.has(f.txn_db_id)}
                      toggle={() => toggle(f.txn_db_id)}
                    />
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </>
      )}
    </div>
  );
}

function Stat({
  label,
  value,
  color,
}: {
  label: string;
  value: number;
  color?: "green" | "yellow" | "red";
}) {
  const c =
    color === "green"
      ? "text-green-700"
      : color === "yellow"
      ? "text-yellow-700"
      : color === "red"
      ? "text-red-700"
      : "text-gray-900";
  return (
    <div className="rounded-lg border bg-white p-4">
      <div className="text-xs text-gray-500">{label}</div>
      <div className={`text-2xl font-bold ${c}`}>{value}</div>
    </div>
  );
}

function FlagRow({
  f,
  checked,
  toggle,
}: {
  f: FlaggedTxn;
  checked: boolean;
  toggle: () => void;
}) {
  return (
    <tr className="border-t align-top">
      <td className="p-2">
        <input type="checkbox" checked={checked} onChange={toggle} />
      </td>
      <td className="p-2 whitespace-nowrap">{f.txn_date}</td>
      <td className="p-2">{f.vendor_raw || "—"}</td>
      <td className="p-2 text-right">${f.amount.toFixed(2)}</td>
      <td className="p-2">
        <span className="text-red-700">{f.original_category || "—"}</span>
      </td>
      <td className="p-2">
        <span className="text-green-700 font-medium">
          {f.suggested_category}
        </span>
      </td>
      <td className="p-2 text-xs text-gray-600 max-w-md">{f.reasoning}</td>
    </tr>
  );
}
