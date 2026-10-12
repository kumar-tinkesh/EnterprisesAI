"use client";

import { ArrowRight, Lightbulb, PenLine, Sparkles } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Spinner } from "@/components/ui/spinner";
import { Textarea } from "@/components/builder/fields";
import { cn } from "@/lib/utils";

const MAX = 4000;

const EXAMPLES = [
  { title: "Inbox assistant", text: "Read my Gmail every morning, summarise the three most urgent emails and draft a reply for each one." },
  { title: "Support agent", text: "Answer customer questions about our products using our policy documents, and never promise refunds." },
  { title: "Lead researcher", text: "Find companies that match a description, look up a decision maker at each, and save them to a sheet." },
  { title: "Standup reporter", text: "Collect what changed in our Jira project yesterday and post a short standup summary to Slack." },
];

/** Step one: a sentence in, a whole drafted agent out. */
export function DescribeStep({
  description,
  onChange,
  generating,
  error,
  hasDraft,
  onGenerate,
  onBlank,
}: {
  description: string;
  onChange: (text: string) => void;
  generating: boolean;
  error: string | null;
  hasDraft: boolean;
  onGenerate: () => void;
  onBlank: () => void;
}) {
  const tooShort = description.trim().length < 3;
  return (
    <div className="space-y-5">
      <form
        className="space-y-2"
        onSubmit={(e) => {
          e.preventDefault();
          if (!tooShort && !generating) onGenerate();
        }}
      >
        <label htmlFor="wizard-description" className="text-xs font-medium text-zinc-700">
          Describe the agent
        </label>
        <Textarea
          id="wizard-description"
          rows={5}
          maxLength={MAX}
          disabled={generating}
          placeholder="e.g. Read our support inbox each morning, sort emails by urgency and draft replies for the urgent ones."
          value={description}
          onChange={(e) => onChange(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && (e.metaKey || e.ctrlKey) && !tooShort && !generating) onGenerate();
          }}
          className="text-sm leading-relaxed"
        />
        <div className="flex items-center justify-between gap-2 text-[11px] text-zinc-400">
          <span>Say what it should do, which apps it works with, and anything it must never do.</span>
          <span className="shrink-0 tabular-nums">{description.length}/{MAX}</span>
        </div>
        <div className="flex flex-col-reverse gap-2 pt-1 sm:flex-row sm:items-center">
          <button
            type="button"
            onClick={onBlank}
            disabled={generating}
            className="inline-flex items-center justify-center gap-1.5 rounded-md px-2 py-2 text-xs font-medium text-zinc-500 hover:text-zinc-900 disabled:opacity-40 cursor-pointer"
          >
            <PenLine className="h-3.5 w-3.5" /> Skip — set it up by hand
          </button>
          <Button type="submit" className="w-full sm:ml-auto sm:w-auto" disabled={tooShort || generating}>
            {generating ? <Spinner className="h-4 w-4" /> : <Sparkles />}
            {generating ? "Designing…" : hasDraft ? "Design it again" : "Design my agent"}
          </Button>
        </div>
        {hasDraft && !generating && (
          <p className="text-[11px] text-amber-700">Designing again replaces the name, tools and settings you have now.</p>
        )}
      </form>

      {generating && (
        <div className="rounded-xl border border-indigo-200 bg-indigo-50 p-3 text-xs text-indigo-900" role="status" aria-live="polite">
          <p className="flex items-center gap-2 font-medium">
            <Spinner className="h-3.5 w-3.5" /> Working out its job, matching your tools and choosing settings…
          </p>
          <p className="mt-1 text-indigo-700">This usually takes 5–15 seconds. You&apos;ll see it appear on the canvas.</p>
        </div>
      )}
      {error && <p className="rounded-lg bg-red-50 p-3 text-xs text-red-700" role="alert">{error}</p>}

      {!generating && (
        <div className="space-y-2">
          <p className="flex items-center gap-1.5 text-xs font-medium text-zinc-500">
            <Lightbulb className="h-3.5 w-3.5" /> Not sure where to start? Use an example
          </p>
          <ul className="grid gap-2 sm:grid-cols-2">
            {EXAMPLES.map((ex) => (
              <li key={ex.title}>
                <button
                  type="button"
                  onClick={() => onChange(ex.text)}
                  className={cn(
                    "group h-full w-full rounded-lg border border-zinc-200 bg-white p-3 text-left transition-colors hover:border-indigo-400 hover:bg-zinc-50 cursor-pointer",
                    description === ex.text && "border-indigo-400",
                  )}
                >
                  <span className="flex items-center justify-between text-xs font-semibold text-zinc-900">
                    {ex.title}
                    <ArrowRight className="h-3.5 w-3.5 text-zinc-400 group-hover:text-indigo-600" />
                  </span>
                  <span className="mt-1 block text-[11px] leading-snug text-zinc-500">{ex.text}</span>
                </button>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
