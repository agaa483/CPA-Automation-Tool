export type Client = {
  id: number;
  firm_name: string;
  qbo_connected: boolean;
  outlook_connected: boolean;
};

export type Category = {
  id: number;
  name: string;
  description: string | null;
};

export type ReceiptSender = { address: string };

export type FlaggedTxn = {
  txn_db_id: number;
  qbo_txn_id: string;
  txn_type: string;
  line_num: number;
  txn_date: string;
  amount: number;
  vendor_raw: string | null;
  original_category: string | null;
  suggested_category: string | null;
  suggested_payee: string | null;
  suggested_payor: string | null;
  reasoning: string;
  supporting_email_ids: string[];
};

export type AuditRunResult = {
  audited: number;
  no_change: number;
  flagged: number;
  errors: number;
  skipped: number;
  flagged_details: FlaggedTxn[];
};

export type AuditLogEntry = {
  id: number;
  transaction_id: number;
  is_correct: boolean;
  original_category: string;
  new_category: string | null;
  reasoning: string;
  action_taken: string;
  created_at: string;
};
