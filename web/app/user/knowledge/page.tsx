"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { BookOpen, FileText, Plus, Search, Upload } from "lucide-react";

import ProtectedDashboard from "@/components/protected-dashboard";
import { useAuthStore } from "@/stores/auth-store";
import {
  knowledgeApi,
  type KnowledgeBase,
  type KnowledgeDocument,
  type KnowledgeSearchResponse,
} from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Dialog } from "@/components/ui/dialog";
import { Menu } from "@/components/ui/menu";
import { Spinner } from "@/components/ui/spinner";
import { Tabs } from "@/components/ui/tabs";
import { Field, Select, Textarea } from "@/components/builder/fields";
import { cn } from "@/lib/utils";

// Mirrors the backend's upload gate (knowledge/services/document_safety.py);
// the server re-checks the actual bytes, this is only an early hint.
const MAX_UPLOAD_BYTES = 25 * 1024 * 1024;
const ALLOWED_EXTENSIONS = [".pdf", ".docx", ".xlsx", ".csv", ".md", ".txt", ".jpg", ".jpeg", ".png"];
const POLL_MS = 3000;

function fileProblem(file: File): string | null {
  if (file.size === 0) return `${file.name} is empty.`;
  if (file.size > MAX_UPLOAD_BYTES) return `${file.name} is larger than the 25 MB limit.`;
  const ext = `.${file.name.split(".").pop()?.toLowerCase() || ""}`;
  if (!ALLOWED_EXTENSIONS.includes(ext)) return `${file.name}: upload PDF, DOCX, XLSX, CSV, Markdown, text, JPG or PNG.`;
  return null;
}

function errorText(err: unknown): string | null {
  if (!err) return null;
  return err instanceof Error ? err.message : String(err);
}

export default function KnowledgeBasesPage() {
  const accessToken = useAuthStore((s) => s.accessToken) || "";
  const queryClient = useQueryClient();
  const [filter, setFilter] = useState("");
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);

  const kbsQuery = useQuery({
    queryKey: ["knowledge-bases", accessToken],
    queryFn: () => knowledgeApi.list(accessToken),
    enabled: !!accessToken,
  });
  const kbs = useMemo(() => kbsQuery.data ?? [], [kbsQuery.data]);
  const visible = kbs.filter((kb) => kb.name.toLowerCase().includes(filter.trim().toLowerCase()));
  const selected = kbs.find((kb) => kb.id === selectedId) ?? null;

  // Keep a selection once there is something to select.
  useEffect(() => {
    if (!selectedId && kbs.length) setSelectedId(kbs[0].id);
    if (selectedId && kbsQuery.isSuccess && !kbs.some((kb) => kb.id === selectedId)) {
      setSelectedId(kbs[0]?.id ?? null);
    }
  }, [kbs, kbsQuery.isSuccess, selectedId]);

  const invalidateList = () => queryClient.invalidateQueries({ queryKey: ["knowledge-bases"] });

  return (
    <ProtectedDashboard
      path="/user"
      title="Knowledge Base"
      description="Documents your agents can look things up in. Everyone in your organisation can search them."
      action={kbs.length > 0 && <Button onClick={() => setCreating(true)}><Plus /> New knowledge base</Button>}
    >
      {creating && (
        <CreateKnowledgeBase
          token={accessToken}
          onClose={() => setCreating(false)}
          onCreated={(kb) => {
            setCreating(false);
            setSelectedId(kb.id);
            invalidateList();
          }}
        />
      )}

      {kbsQuery.isLoading ? (
        <div className="flex justify-center py-16">
          <Spinner className="h-6 w-6 text-zinc-500" />
        </div>
      ) : kbsQuery.isError ? (
        <p className="mt-6 rounded-lg border border-red-200 bg-red-50 p-4 text-sm text-red-700">
          {errorText(kbsQuery.error)}
        </p>
      ) : kbs.length === 0 ? (
        <div className="mt-6 flex flex-col items-center rounded-lg border border-dashed border-zinc-300 px-6 py-14 text-center">
          <BookOpen className="h-6 w-6 text-zinc-400" />
          <h2 className="mt-3 text-base font-semibold text-zinc-900">No knowledge bases yet</h2>
          <p className="mt-1 max-w-sm text-sm text-zinc-500">Create one, then upload documents or paste text into it.</p>
          <Button className="mt-5" onClick={() => setCreating(true)}>
            <Plus /> New knowledge base
          </Button>
        </div>
      ) : (
        <div className="mt-6 grid gap-6 lg:grid-cols-[288px_minmax(0,1fr)]">
          {/* Phones and tablets: a picker instead of a column. */}
          <div className="lg:hidden">
            <Select value={selectedId ?? ""} onChange={(e) => setSelectedId(e.target.value)} aria-label="Knowledge base">
              {kbs.map((kb) => (
                <option key={kb.id} value={kb.id}>
                  {kb.name} ({kb.document_count})
                </option>
              ))}
            </Select>
          </div>

          <aside className="hidden min-w-0 lg:block">
            {kbs.length > 6 && (
              <div className="relative mb-2">
                <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-zinc-400" />
                <Input className="pl-9" placeholder="Filter" value={filter} onChange={(e) => setFilter(e.target.value)} aria-label="Filter knowledge bases" />
              </div>
            )}
            <ul className="space-y-0.5">
              {visible.map((kb) => (
                <li key={kb.id}>
                  <button
                    type="button"
                    onClick={() => setSelectedId(kb.id)}
                    aria-current={kb.id === selectedId ? "true" : undefined}
                    className={cn(
                      "flex w-full items-center justify-between gap-2 rounded-md px-3 py-2 text-left text-sm transition-colors cursor-pointer",
                      kb.id === selectedId ? "bg-white/[0.08] text-white font-medium" : "text-zinc-400 hover:bg-white/[0.04] hover:text-zinc-200",
                    )}
                  >
                    <span className="truncate font-medium">{kb.name}</span>
                    <span className="shrink-0 text-xs tabular-nums text-zinc-400">{kb.document_count}</span>
                  </button>
                </li>
              ))}
              {visible.length === 0 && <li className="px-3 py-4 text-sm text-zinc-400">No match.</li>}
            </ul>
          </aside>

          {selected && (
            <KnowledgeBaseDetail
              key={selected.id}
              kb={selected}
              token={accessToken}
              onChanged={invalidateList}
            />
          )}
        </div>
      )}
    </ProtectedDashboard>
  );
}

function CreateKnowledgeBase({
  token,
  onClose,
  onCreated,
}: {
  token: string;
  onClose: () => void;
  onCreated: (kb: KnowledgeBase) => void;
}) {
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const create = useMutation({
    mutationFn: () => knowledgeApi.create(token, { name, description }),
    onSuccess: onCreated,
  });

  return (
    <Dialog title="New knowledge base" onClose={onClose}>
      <form
        onSubmit={(e) => {
          e.preventDefault();
          if (name.trim()) create.mutate();
        }}
        className="space-y-4"
      >
        <Field label="Name">
          <Input placeholder="e.g. HR policies" value={name} onChange={(e) => setName(e.target.value)} autoFocus required />
        </Field>
        <Field label="Description" hint="Optional. What's in it.">
          <Input value={description} onChange={(e) => setDescription(e.target.value)} />
        </Field>
        {create.isError && <p className="text-sm text-red-600">{errorText(create.error)}</p>}
        <div className="flex justify-end gap-2">
          <Button type="button" variant="outline" onClick={onClose}>
            Cancel
          </Button>
          <Button type="submit" disabled={create.isPending || !name.trim()}>
            {create.isPending && <Spinner className="h-4 w-4" />} Create
          </Button>
        </div>
      </form>
    </Dialog>
  );
}

type Tab = "documents" | "search";

function KnowledgeBaseDetail({
  kb,
  token,
  onChanged,
}: {
  kb: KnowledgeBase;
  token: string;
  onChanged: () => void;
}) {
  const [tab, setTab] = useState<Tab>("documents");
  const [renaming, setRenaming] = useState(false);
  const [name, setName] = useState(kb.name);
  const [description, setDescription] = useState(kb.description);

  const update = useMutation({
    mutationFn: () => knowledgeApi.update(token, kb.id, { name, description }),
    onSuccess: () => {
      setRenaming(false);
      onChanged();
    },
  });
  const remove = useMutation({
    mutationFn: () => knowledgeApi.remove(token, kb.id),
    onSuccess: onChanged,
  });

  return (
    <section className="min-w-0 space-y-5">
      <header className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <h2 className="text-base font-semibold text-zinc-900">{kb.name}</h2>
          {kb.description && <p className="mt-0.5 text-sm text-zinc-500">{kb.description}</p>}
          {remove.isError && <p className="mt-1 text-sm text-red-600">{errorText(remove.error)}</p>}
        </div>
        {kb.can_manage && (
          <div className="flex shrink-0 items-center gap-1">
            {remove.isPending && <Spinner className="h-4 w-4 text-zinc-400" />}
            <Menu
              label={`More for ${kb.name}`}
              items={[
                { label: "Rename", onClick: () => setRenaming(true) },
                { label: "Delete", danger: true, onClick: () => confirm(`Delete "${kb.name}" and all of its documents?`) && remove.mutate() },
              ]}
            />
          </div>
        )}
      </header>

      {renaming && (
        <Dialog title="Rename knowledge base" onClose={() => setRenaming(false)}>
          <form
            onSubmit={(e) => {
              e.preventDefault();
              if (name.trim()) update.mutate();
            }}
            className="space-y-4"
          >
            <Field label="Name">
              <Input value={name} onChange={(e) => setName(e.target.value)} autoFocus required />
            </Field>
            <Field label="Description">
              <Input value={description} onChange={(e) => setDescription(e.target.value)} />
            </Field>
            {update.isError && <p className="text-sm text-red-600">{errorText(update.error)}</p>}
            <div className="flex justify-end gap-2">
              <Button type="button" variant="outline" onClick={() => setRenaming(false)}>
                Cancel
              </Button>
              <Button type="submit" disabled={update.isPending || !name.trim()}>
                {update.isPending && <Spinner className="h-4 w-4" />} Save
              </Button>
            </div>
          </form>
        </Dialog>
      )}

      <Tabs value={tab} onChange={setTab} tabs={[["documents", "Documents"], ["search", "Test search"]] as const} />

      <div key={tab} className="animate-fade-in">
        {tab === "documents" ? (
          <DocumentsPanel kb={kb} token={token} onChanged={onChanged} />
        ) : (
          <SearchPanel kb={kb} token={token} />
        )}
      </div>
    </section>
  );
}

function DocumentsPanel({ kb, token, onChanged }: { kb: KnowledgeBase; token: string; onChanged: () => void }) {
  const queryClient = useQueryClient();
  const fileRef = useRef<HTMLInputElement>(null);
  const [isDragging, setIsDragging] = useState(false);
  const [uploadError, setUploadError] = useState<string | null>(null);
  // null = closed; { id: null } = new text; { id } = editing that document.
  const [editor, setEditor] = useState<{ id: string | null; title: string; content: string } | null>(null);

  const docsKey = ["knowledge-documents", kb.id];
  const docsQuery = useQuery({
    queryKey: docsKey,
    queryFn: () => knowledgeApi.listDocuments(token, kb.id),
    enabled: !!token,
    // Keep refreshing while anything is still being indexed.
    refetchInterval: (q) => (q.state.data?.some((d) => d.status === "processing") ? POLL_MS : false),
  });
  const docs = docsQuery.data ?? [];

  const refresh = () => {
    queryClient.invalidateQueries({ queryKey: docsKey });
    onChanged();
  };

  const upload = useMutation({
    mutationFn: async (files: File[]) => {
      for (const f of files) await knowledgeApi.uploadDocument(token, kb.id, f);
    },
    onSuccess: refresh,
    onError: (err) => {
      setUploadError(errorText(err));
      refresh();
    },
  });

  const saveText = useMutation({
    mutationFn: (e: { id: string | null; title: string; content: string }) =>
      e.id
        ? knowledgeApi.updateText(token, kb.id, e.id, { title: e.title, content: e.content })
        : knowledgeApi.addText(token, kb.id, { title: e.title, content: e.content }),
    onSuccess: () => {
      setEditor(null);
      refresh();
    },
  });

  const openText = useMutation({
    mutationFn: (doc: KnowledgeDocument) => knowledgeApi.getText(token, kb.id, doc.id),
    onSuccess: (t) => setEditor({ id: t.id, title: t.title, content: t.content }),
  });

  const removeDoc = useMutation({
    mutationFn: (doc: KnowledgeDocument) => knowledgeApi.removeDocument(token, kb.id, doc.id),
    onSuccess: refresh,
  });

  function addFiles(files: File[]) {
    if (!files.length) return;
    const problems = files.map(fileProblem).filter(Boolean);
    if (problems.length) {
      setUploadError(problems.join(" "));
      return;
    }
    setUploadError(null);
    upload.mutate(files);
  }

  const actionError = errorText(openText.error) || errorText(removeDoc.error);

  return (
    <div className="space-y-4">
      <input
        ref={fileRef}
        type="file"
        multiple
        className="hidden"
        accept={ALLOWED_EXTENSIONS.join(",")}
        onChange={(e) => {
          const files = Array.from(e.target.files || []);
          e.target.value = "";
          addFiles(files);
        }}
      />

      {/* Drag & Drop Upload Zone */}
      <div
        onDragOver={(e) => {
          e.preventDefault();
          setIsDragging(true);
        }}
        onDragLeave={() => setIsDragging(false)}
        onDrop={(e) => {
          e.preventDefault();
          setIsDragging(false);
          const files = Array.from(e.dataTransfer.files || []);
          addFiles(files);
        }}
        className={cn(
          "flex flex-col items-center justify-center rounded-xl border-2 border-dashed p-6 text-center transition-all duration-200",
          isDragging
            ? "scale-[1.01] border-indigo-500/70 bg-indigo-500/10 shadow-[0_0_28px_-4px_rgba(99,102,241,0.3)]"
            : "border-white/10 hover:border-white/20 bg-white/[0.02] hover:bg-white/[0.04]"
        )}
      >
        <Upload className={cn("h-7 w-7 transition-transform duration-200", isDragging ? "scale-110 text-indigo-400 animate-bounce" : "text-zinc-400")} />
        <p className="mt-2 text-xs font-medium text-zinc-200">
          Drag & drop files here, or{" "}
          <button
            type="button"
            disabled={upload.isPending}
            onClick={() => fileRef.current?.click()}
            className="text-indigo-400 underline underline-offset-2 hover:text-indigo-300 cursor-pointer"
          >
            browse to upload
          </button>
        </p>
        <p className="mt-1 text-[11px] text-zinc-400">PDF, DOCX, XLSX, CSV, Markdown, text, JPG, PNG · up to 25 MB</p>
        {upload.isPending && (
          <div className="mt-3 flex items-center gap-2 text-xs text-indigo-400 font-medium">
            <Spinner className="h-4 w-4" /> Uploading & indexing documents…
          </div>
        )}
      </div>

      <div className="flex items-center justify-between">
        <span className="text-xs font-semibold text-zinc-200">
          Documents {docs.length > 0 && <span className="font-normal text-zinc-400">({docs.length})</span>}
        </span>
        <Button size="sm" variant="outline" onClick={() => setEditor({ id: null, title: "", content: "" })}>
          <Plus /> Paste text
        </Button>
      </div>
      {uploadError && <p className="text-sm text-red-600">{uploadError}</p>}

      {editor && (
        <Dialog title={editor.id ? "Edit text" : "Add text"} onClose={() => setEditor(null)}>
          <form
            onSubmit={(e) => {
              e.preventDefault();
              saveText.mutate(editor);
            }}
            className="space-y-4"
          >
            <Field label="Title">
              <Input value={editor.title} maxLength={120} onChange={(e) => setEditor({ ...editor, title: e.target.value })} autoFocus required />
            </Field>
            <Field label="Text">
              <Textarea
                className="min-h-48"
                placeholder="Paste or type what your agents should know"
                value={editor.content}
                onChange={(e) => setEditor({ ...editor, content: e.target.value })}
                required
              />
            </Field>
            {saveText.isError && <p className="text-sm text-red-600">{errorText(saveText.error)}</p>}
            <div className="flex justify-end gap-2">
              <Button type="button" variant="outline" onClick={() => setEditor(null)}>
                Cancel
              </Button>
              <Button type="submit" disabled={saveText.isPending || !editor.title.trim() || !editor.content.trim()}>
                {saveText.isPending && <Spinner className="h-4 w-4" />} {editor.id ? "Save" : "Add"}
              </Button>
            </div>
          </form>
        </Dialog>
      )}

      {actionError && <p className="text-sm text-red-600">{actionError}</p>}

      {docsQuery.isLoading ? (
        <div className="flex justify-center py-8">
          <Spinner className="h-5 w-5 text-zinc-400" />
        </div>
      ) : docs.length === 0 ? (
        <p className="rounded-lg border border-dashed border-white/10 bg-white/[0.01] px-4 py-10 text-center text-sm text-zinc-400">
          No documents yet. Upload a file or add some text.
        </p>
      ) : (
        <ul className="divide-y divide-white/5 overflow-hidden rounded-lg border border-white/10 bg-[var(--surface)]">
          {docs.map((doc) => (
            <li key={doc.id} className="group flex items-start gap-3 px-4 py-3 transition-colors hover:bg-white/[0.04]">
              <FileText className="mt-0.5 h-4 w-4 shrink-0 text-zinc-400" />
              <div className="min-w-0 flex-1">
                <p className="truncate text-sm font-medium text-zinc-100 group-hover:text-white">{doc.filename}</p>
                <p className="mt-0.5 flex flex-wrap items-center gap-x-3 text-xs text-zinc-400">
                  <Status doc={doc} />
                  {doc.status === "ready" && <span>{doc.chunk_count} chunk{doc.chunk_count === 1 ? "" : "s"}</span>}
                </p>
                {doc.error_message && (
                  <p className={cn("mt-1 text-xs", doc.status === "error" ? "text-red-400" : "text-amber-400")}>{doc.error_message}</p>
                )}
              </div>
              <Menu
                label={`More for ${doc.filename}`}
                items={[
                  ...(doc.editable && doc.status !== "processing" ? [{ label: "Edit", onClick: () => openText.mutate(doc) }] : []),
                  { label: "Delete", danger: true, onClick: () => confirm(`Delete "${doc.filename}"?`) && removeDoc.mutate(doc) },
                ]}
              />
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

/** A document's state as a coloured dot and a word. */
function Status({ doc }: { doc: KnowledgeDocument }) {
  if (doc.status === "processing") {
    return (
      <span className="inline-flex items-center gap-1.5 text-zinc-300">
        <Spinner className="h-3 w-3 text-indigo-400" /> Indexing
      </span>
    );
  }
  const failed = doc.status === "error";
  return (
    <span className={cn("inline-flex items-center gap-1.5", failed ? "text-red-400" : "text-zinc-300")}>
      <span className={cn("h-1.5 w-1.5 rounded-full", failed ? "bg-red-400" : "bg-emerald-400")} aria-hidden />
      {failed ? "Failed" : "Ready"}
    </span>
  );
}

function SearchPanel({ kb, token }: { kb: KnowledgeBase; token: string }) {
  const [query, setQuery] = useState("");
  const search = useMutation<KnowledgeSearchResponse, Error, string>({
    mutationFn: (q) => knowledgeApi.search(token, kb.id, { query: q, top_k: 5 }),
  });

  return (
    <div className="space-y-4">
      <p className="text-sm text-zinc-500">
        Ask something the way an agent would — you&apos;ll see the passages it would get back.
      </p>
      <form
        onSubmit={(e) => {
          e.preventDefault();
          if (query.trim()) search.mutate(query.trim());
        }}
        className="flex gap-2"
      >
        <Input placeholder="e.g. What is the refund window?" value={query} onChange={(e) => setQuery(e.target.value)} />
        <Button type="submit" disabled={search.isPending || !query.trim()}>
          {search.isPending ? <Spinner className="h-4 w-4" /> : <Search />} <span className="hidden sm:inline">Search</span>
        </Button>
      </form>
      {search.isError && <p className="text-sm text-red-600">{errorText(search.error)}</p>}

      {search.data &&
        (search.data.results.length === 0 ? (
          <p className="py-8 text-center text-sm text-zinc-500">
            Nothing found. Documents still indexing aren&apos;t searchable yet.
          </p>
        ) : (
          <ol className="space-y-3">
            {search.data.results.map((hit, i) => {
              const pct = Math.round(hit.score * 100);
              const high = hit.score >= 0.7;
              return (
                <li
                  key={hit.id}
                  style={{ animationDelay: `${i * 45}ms` }}
                  className="card-lift animate-fade-up rounded-xl border border-white/10 bg-[var(--surface)] p-4 hover:border-white/20"
                >
                  <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-zinc-400">
                    <span className="font-medium text-zinc-100">#{i + 1}</span>
                    <span className="min-w-0 truncate font-medium text-zinc-200">{hit.filename}</span>
                    <span className="rounded bg-white/[0.05] px-1.5 py-0.5 text-[10px] text-zinc-400">{hit.retrieval_method}</span>
                    <span className={cn("ml-auto rounded-full px-2 py-0.5 text-[11px] font-medium tabular-nums border", high ? "border-emerald-500/20 bg-emerald-500/10 text-emerald-400" : "border-amber-500/20 bg-amber-500/10 text-amber-300")}>
                      {pct}% match ({hit.score.toFixed(3)})
                    </span>
                  </div>
                  <p className="mt-2.5 whitespace-pre-wrap break-words rounded bg-white/[0.02] p-3 font-mono text-xs text-zinc-300 border border-white/10">{hit.content}</p>
                </li>
              );
            })}
          </ol>
        ))}
    </div>
  );
}
