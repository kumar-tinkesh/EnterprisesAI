"use client";

import { Background, BackgroundVariant, Controls, ReactFlow, ReactFlowProvider } from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import { ArrowLeft, Bot, Link2, Network, Server, Sparkles } from "lucide-react";

import { Button } from "@/components/ui/button";
import { BuildBar } from "@/components/builder/build-bar";
import type { BuildTarget } from "@/lib/builder/use-builder-actions";

/**
 * The AI Compiler's empty canvas: describe an agent or workflow in the bar
 * at the bottom and it opens right here (only the URL changes).
 */
export default function BuilderHome({
  hasAnyConnectedServer,
  onConnections,
  onOpen,
}: {
  hasAnyConnectedServer: boolean;
  onConnections: () => void;
  onOpen: (target: BuildTarget) => void;
}) {
  return (
    <div className="builder-dark flex h-screen flex-col bg-zinc-950">
      <header className="flex items-center gap-2 border-b border-zinc-200 bg-white px-3 py-2">
        <a href="/user" className="rounded-md p-1.5 text-zinc-500 hover:bg-zinc-100 hover:text-zinc-900 cursor-pointer" aria-label="Back to workspace" title="Back to workspace">
          <ArrowLeft className="h-4 w-4" />
        </a>
        <Sparkles className="h-4 w-4 text-indigo-600" />
        <span className="text-sm font-semibold text-zinc-900">AI Compiler</span>
        <span className="text-xs text-zinc-400">Describe an agent or workflow below</span>
        <div className="ml-auto flex gap-2">
          <Button size="sm" variant="outline" className="h-8" onClick={onConnections}>
            <Server /> Connections
          </Button>
        </div>
      </header>

      {!hasAnyConnectedServer && (
        <div className="flex items-center gap-3 border-b border-amber-200 bg-amber-50 px-4 py-2 text-xs text-amber-800">
          <p className="flex-1">You haven&apos;t connected any MCP server yet — agents and workflows need one to call tools.</p>
          <button type="button" onClick={onConnections} className="inline-flex items-center gap-1 font-medium underline cursor-pointer">
            <Link2 className="h-3 w-3" /> Connect a server
          </button>
        </div>
      )}

      <div className="relative min-h-0 flex-1">
        <ReactFlowProvider>
          <ReactFlow nodes={[]} edges={[]} colorMode="dark" proOptions={{ hideAttribution: true }}>
            <Background variant={BackgroundVariant.Dots} gap={22} size={1.2} color="#3f3f46" />
            <Controls showInteractive={false} />
          </ReactFlow>
        </ReactFlowProvider>
        <div className="pointer-events-none absolute inset-0 flex flex-col items-center justify-center gap-3 text-center">
          <div className="flex gap-2 text-indigo-400">
            <Bot className="h-6 w-6" />
            <Network className="h-6 w-6" />
          </div>
          <p className="text-sm font-medium text-zinc-300">What do you want to build?</p>
          <p className="max-w-sm text-xs text-zinc-500">
            Pick Agent or Workflow below and describe it. It&apos;s designed, matched to your tools and opened on this canvas.
          </p>
        </div>
      </div>

      <BuildBar current={null} onOpen={onOpen} />
    </div>
  );
}
