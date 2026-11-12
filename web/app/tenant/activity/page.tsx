"use client";

import ProtectedDashboard from "@/components/protected-dashboard";
import { AuditLogsPanel } from "@/components/audit-logs-panel";

export default function TenantActivity() {
  return (
    <ProtectedDashboard path="/tenant" title="Activity" description="Your organization's sign-ins and changes, newest first.">
      <div className="mt-6">
        <AuditLogsPanel limit={40} title="Everything" />
      </div>
    </ProtectedDashboard>
  );
}
