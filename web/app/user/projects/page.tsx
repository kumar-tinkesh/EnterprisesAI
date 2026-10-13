"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";

/** Old link: Projects is Executions now (the open chat, if any, carries over). */
export default function ProjectsRedirect() {
  const router = useRouter();
  useEffect(() => router.replace(`/user/executions${window.location.search}`), [router]);
  return null;
}
