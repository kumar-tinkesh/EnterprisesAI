"use client";

import { useQuery } from "@tanstack/react-query";

import { api, type AuditLog } from "@/lib/api";
import { useAuthStore } from "@/stores/auth-store";
import { Spinner } from "@/components/ui/spinner";

function formatTime(ts: string | null): string {
  if (!ts) return "—";
  try {
    return new Date(ts).toLocaleString();
  } catch {
    return ts;
  }
}

/** Reads the current user's latest audit-log entries (role-scoped server-side). */
export function AuditLogsPanel({ limit = 25 }: { limit?: number }) {
  const accessToken = useAuthStore((s) => s.accessToken) || "";

  const { data: logs = [], isLoading, isError } = useQuery({
    queryKey: ["audit-logs", accessToken, limit],
    queryFn: () => api.getAuditLogs(accessToken, { limit }),
    enabled: !!accessToken,
  });

  return (
    <div className="mt-6 rounded-xl border border-zinc-200 bg-white p-6">
      <h2 className="text-lg font-semibold text-zinc-900">Audit Log</h2>
      {isLoading ? (
        <div className="mt-4 flex items-center gap-2 text-sm text-zinc-500">
          <Spinner className="h-4 w-4" /> Loading audit events...
        </div>
      ) : isError ? (
        <p className="mt-4 text-sm text-red-600">
          Failed to load audit logs. Only admins with a tenant can view them.
        </p>
      ) : logs.length === 0 ? (
        <p className="mt-4 text-sm text-zinc-400">No audit events yet.</p>
      ) : (
        <ul className="mt-4 divide-y divide-zinc-100">
          {logs.slice(0, limit).map((log: AuditLog) => (
            <li key={log.id} className="flex items-start justify-between gap-4 py-2 text-sm">
              <div>
                <span className="font-medium text-zinc-800">{log.action}</span>
                {log.resource && (
                  <span className="ml-2 text-xs text-zinc-400">on {log.resource}</span>
                )}
              </div>
              <div className="shrink-0 text-right text-xs text-zinc-400">
                <span>{formatTime(log.created_at)}</span>
                {log.ip_address && (
                  <span className="block">{log.ip_address}</span>
                )}
              </div>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
