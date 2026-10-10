"use client";

import { useEffect } from "react";
import { useParams, useRouter } from "next/navigation";

import { editorHref } from "@/lib/builder/use-builder-actions";

/** Old link: agents open on the AI Compiler canvas now. */
export default function AgentRedirect() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  useEffect(() => router.replace(editorHref({ kind: "agent", id })), [id, router]);
  return null;
}
