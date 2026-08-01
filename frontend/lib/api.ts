"use client";

import { useAuth } from "@clerk/nextjs";
import { useMemo } from "react";
import type {
  Client,
  Category,
  ReceiptSender,
  AuditRunResult,
  AuditLogEntry,
} from "./types";

const BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8001";

type TokenGetter = () => Promise<string | null>;

/** Build the API client with a token getter (Clerk session). */
export function makeApi(getToken: TokenGetter) {
  async function req<T>(path: string, opts: RequestInit = {}): Promise<T> {
    const token = await getToken();
    const headers: Record<string, string> = {
      "Content-Type": "application/json",
      ...(opts.headers as Record<string, string> | undefined),
    };
    if (token) headers["Authorization"] = `Bearer ${token}`;

    const r = await fetch(`${BASE}${path}`, { ...opts, headers });
    if (!r.ok) {
      const txt = await r.text();
      throw new Error(`${r.status}: ${txt}`);
    }
    if (r.status === 204) return undefined as T;
    return r.json();
  }

  async function uploadForm(path: string, form: FormData): Promise<Blob> {
    const token = await getToken();
    const headers: Record<string, string> = {};
    if (token) headers["Authorization"] = `Bearer ${token}`;
    const r = await fetch(`${BASE}${path}`, { method: "POST", body: form, headers });
    if (!r.ok) throw new Error(`${r.status}: ${await r.text()}`);
    return r.blob();
  }

  return {
    qboAuthUrl: (clientId: number) =>
      req<{ auth_url: string }>(`/oauth/qbo/start?client_id=${clientId}`),
    outlookAuthUrl: (clientId: number) =>
      req<{ auth_url: string }>(`/oauth/outlook/start?client_id=${clientId}`),

    listClients: () => req<Client[]>("/clients"),
    createClient: (firm_name: string) =>
      req<Client>("/clients", { method: "POST", body: JSON.stringify({ firm_name }) }),
    getClient: (id: number) => req<Client>(`/clients/${id}`),

    listCategories: (clientId: number) =>
      req<Category[]>(`/clients/${clientId}/categories`),
    syncCategories: (clientId: number) =>
      req<{ synced: number }>(`/clients/${clientId}/categories/sync`, { method: "POST" }),

    listSenders: (clientId: number) =>
      req<ReceiptSender[]>(`/clients/${clientId}/receipt-senders`),
    addSender: (clientId: number, address: string) =>
      req<ReceiptSender>(`/clients/${clientId}/receipt-senders`, {
        method: "POST",
        body: JSON.stringify({ address }),
      }),
    removeSender: (clientId: number, address: string) =>
      req<void>(
        `/clients/${clientId}/receipt-senders/${encodeURIComponent(address)}`,
        { method: "DELETE" }
      ),

    runAudit: (clientId: number) =>
      req<AuditRunResult>(`/clients/${clientId}/audits/run`, { method: "POST" }),
    applyCorrections: (clientId: number, txn_db_ids: number[]) =>
      req<{ applied: number; failed: number; details: any[] }>(
        `/clients/${clientId}/audits/apply`,
        { method: "POST", body: JSON.stringify({ txn_db_ids }) }
      ),
    auditHistory: (clientId: number, limit = 50) =>
      req<AuditLogEntry[]>(`/clients/${clientId}/audits/history?limit=${limit}`),

    uploadExcel: async (clientId: number, file: File, auditExisting: boolean) => {
      const form = new FormData();
      form.append("file", file);
      form.append("audit_existing", String(auditExisting));
      return uploadForm(`/clients/${clientId}/excel/audit`, form);
    },
  };
}

/** React hook: returns an API client that auto-attaches the current Clerk token. */
export function useApi() {
  const { getToken } = useAuth();
  return useMemo(() => makeApi(() => getToken()), [getToken]);
}
