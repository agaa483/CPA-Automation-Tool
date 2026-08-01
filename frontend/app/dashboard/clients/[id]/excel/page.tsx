"use client";
import { useState } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useApi } from "@/lib/api";

export default function ExcelPage() {
  const api = useApi();
  const params = useParams();
  const id = Number(params.id);

  const [file, setFile] = useState<File | null>(null);
  const [auditExisting, setAuditExisting] = useState(true);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!file) return;
    setBusy(true);
    setErr(null);
    try {
      const blob = await api.uploadExcel(id, file, auditExisting);
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `${file.name.replace(/\.xlsx$/i, "")}_suggestions.xlsx`;
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);
    } catch (e) {
      setErr(String(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="space-y-6 max-w-xl">
      <div>
        <Link
          href={`/dashboard/clients/${id}`}
          className="text-sm text-gray-500 hover:underline"
        >
          ← Client
        </Link>
        <h1 className="text-2xl font-semibold mt-1">Audit spreadsheet</h1>
      </div>

      <p className="text-sm text-gray-600">
        Upload a bank export (.xlsx). We'll add columns for Suggested Payee,
        Suggested Payor, Suggested Category, and Reasoning, then hand the
        annotated file back for download.
      </p>

      <form onSubmit={submit} className="space-y-4">
        <input
          type="file"
          accept=".xlsx"
          onChange={(e) => setFile(e.target.files?.[0] || null)}
          className="block w-full text-sm"
          required
        />
        <label className="flex items-center gap-2 text-sm">
          <input
            type="checkbox"
            checked={auditExisting}
            onChange={(e) => setAuditExisting(e.target.checked)}
          />
          Audit rows that already have a category (check correctness). Uncheck
          to only suggest categories for uncategorized rows.
        </label>
        {err && <p className="text-red-600 text-sm">{err}</p>}
        <button
          type="submit"
          disabled={!file || busy}
          className="rounded-md bg-black px-4 py-2 text-white text-sm font-medium disabled:opacity-50"
        >
          {busy ? "Running… (can take a few minutes)" : "Run audit + download"}
        </button>
      </form>
    </div>
  );
}
