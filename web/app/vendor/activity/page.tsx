"use client";

import { useQuery } from "@tanstack/react-query";

import ProtectedDashboard from "@/components/protected-dashboard";
import { AuditLogsPanel } from "@/components/audit-logs-panel";
import { useAuthStore } from "@/stores/auth-store";
import { vendorApi } from "@/lib/api";
import { appLabel } from "@/lib/connectors";

export default function VendorActivity() {
  const accessToken = useAuthStore((s) => s.accessToken) || "";
  const { data: servers = [] } = useQuery({ queryKey: ["vendor-mcp-servers", accessToken], queryFn: () => vendorApi.listMCPServers(accessToken), enabled: !!accessToken });
  const names = Object.fromEntries(servers.map((s) => [s.id, appLabel(s.name, s.description).title]));
  return (
    <ProtectedDashboard path="/vendor" title="Activity" description="Sign-ins, apps added and tested, and access changes, newest first.">
      <div className="mt-6">
        <AuditLogsPanel limit={40} names={names} title="Everything" />
      </div>
    </ProtectedDashboard>
  );
}
