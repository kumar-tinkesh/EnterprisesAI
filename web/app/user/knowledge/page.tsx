"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  AlertTriangle,
  BookOpen,
  CheckCircle2,
  FileText,
  Pencil,
  Plus,
  Search,
  Trash2,
  Upload,
  X,
} from "lucide-react";

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
import { Spinner } from "@/components/ui/spinner";
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
      description="Documents your agents can retrieve from. Every member of your organisation can search them."
    >
      <div className="mt-6 flex items-center justify-between gap-3">
        <a href="/user" className="text-sm text-zinc-500 hover:text-zinc-800">
          ← Back to workspace
        </a>
        <Button size="sm" onClick={() => setCreating(true)}>
          <Plus /> New knowledge base
        </Button>
      </div>

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
        <div className="mt-6 rounded-xl border border-dashed border-zinc-300 bg-white p-10 text-center">
          <BookOpen className="mx-auto h-8 w-8 text-violet-500" />
          <h2 className="mt-3 font-semibold text-zinc-900">No knowledge bases yet</h2>
          <p className="mt-1 text-sm text-zinc-500">
            Create one, then upload documents or paste text into it.
          </p>
          <Button size="sm" className="mt-4" onClick={() => setCreating(true)}>
            <Plus /> New knowledge base
          </Button>
        </div>
      ) : (
        <div className="mt-6 grid gap-6 lg:grid-cols-[300px_minmax(0,1fr)]">
          <aside className="min-w-0">
            <div className="relative">
              <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-zinc-400" />
              <Input
                className="pl-9"
                placeholder="Filter by name…"
                value={filter}
                onChange={(e) => setFilter(e.target.value)}
              />
            </div>
            <ul className="mt-3 space-y-2">
              {visible.map((kb) => (
                <li key={kb.id}>
                  <button
                    onClick={() => setSelectedId(kb.id)}
                    className={cn(
                      "w-full rounded-lg border bg-white p-3 text-left transition-colors cursor-pointer",
                      kb.id === selectedId ? "border-violet-400 ring-1 ring-violet-200" : "border-zinc-200 hover:border-zinc-300",
                    )}
                  >
                    <p className="truncate text-sm font-medium text-zinc-900">{kb.name}</p>
                    <p className="mt-0.5 text-xs text-zinc-500">
                      {kb.document_count} document{kb.document_count === 1 ? "" : "s"}
                    </p>
                  </button>
                </li>
              ))}
              {visible.length === 0 && <li className="py-4 text-center text-sm text-zinc-400">No match.</li>}
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
    <form
      onSubmit={(e) => {
        e.preventDefault();
        if (name.trim()) create.mutate();
      }}
      className="mt-4 rounded-xl border border-zinc-200 bg-white p-5"
    >
      <div className="flex items-center justify-between">
        <h2 className="font-semibold text-zinc-900">New knowledge base</h2>
        <button type="button" onClick={onClose} className="text-zinc-400 hover:text-zinc-700 cursor-pointer" aria-label="Close">
          <X className="h-4 w-4" />
        </button>
      </div>
      <div className="mt-3 grid gap-3 sm:grid-cols-2">
        <Input placeholder="Name, e.g. HR policies" value={name} onChange={(e) => setName(e.target.value)} autoFocus required />
        <Input placeholder="What's in it (optional)" value={description} onChange={(e) => setDescription(e.target.value)} />
      </div>
      {create.isError && <p className="mt-2 text-xs text-red-600">{errorText(create.error)}</p>}
      <div className="mt-3 flex justify-end gap-2">
        <Button type="button" variant="outline" size="sm" onClick={onClose}>
          Cancel
        </Button>
        <Button type="submit" size="sm" disabled={create.isPending || !name.trim()}>
          {create.isPending ? <Spinner /> : "Create"}
        </Button>
      </div>
    </form>
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
    <section className="min-w-0 rounded-xl border border-zinc-200 bg-white">
      <header className="border-b border-zinc-100 p-5">
        {renaming ? (
          <form
            onSubmit={(e) => {
              e.preventDefault();
              if (name.trim()) update.mutate();
            }}
            className="space-y-2"
          >
            <Input value={name} onChange={(e) => setName(e.target.value)} required />
            <Input placeholder="Description" value={description} onChange={(e) => setDescription(e.target.value)} />
            {update.isError && <p className="text-xs text-red-600">{errorText(update.error)}</p>}
            <div className="flex gap-2">
              <Button type="submit" size="sm" disabled={update.isPending}>
                {update.isPending ? <Spinner /> : "Save"}
              </Button>
              <Button type="button" variant="outline" size="sm" onClick={() => setRenaming(false)}>
                Cancel
              </Button>
            </div>
          </form>
        ) : (
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div className="min-w-0">
              <h2 className="truncate text-lg font-semibold text-zinc-900">{kb.name}</h2>
              {kb.description && <p className="mt-0.5 text-sm text-zinc-500">{kb.description}</p>}
            </div>
            {kb.can_manage && (
              <div className="flex gap-2">
                <Button variant="outline" size="sm" onClick={() => setRenaming(true)}>
                  <Pencil /> Rename
                </Button>
                <Button
                  variant="outline"
                  size="sm"
                  className="text-red-600 hover:bg-red-50"
                  disabled={remove.isPending}
                  onClick={() => {
                    if (confirm(`Delete "${kb.name}" and all of its documents?`)) remove.mutate();
                  }}
                >
                  {remove.isPending ? <Spinner /> : <Trash2 />} Delete
                </Button>
              </div>
            )}
          </div>
        )}
        {remove.isError && <p className="mt-2 text-xs text-red-600">{errorText(remove.error)}</p>}

        <nav className="mt-4 flex gap-1">
          {(
            [
              ["documents", "Documents", FileText],
              ["search", "Test search", Search],
            ] as const
          ).map(([id, label, Icon]) => (
            <button
              key={id}
              onClick={() => setTab(id)}
              className={cn(
                "inline-flex items-center gap-1.5 rounded-md px-3 py-1.5 text-sm font-medium cursor-pointer",
                tab === id ? "bg-zinc-900 text-white" : "text-zinc-500 hover:bg-zinc-100 hover:text-zinc-800",
              )}
            >
              <Icon className="h-3.5 w-3.5" /> {label}
            </button>
          ))}
        </nav>
      </header>

      <div className="p-5">
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

  function pickFiles(e: React.ChangeEvent<HTMLInputElement>) {
    const files = Array.from(e.target.files || []);
    e.target.value = "";
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
    <div>
      <div className="flex flex-wrap items-center gap-2">
        <input
          ref={fileRef}
          type="file"
          multiple
          className="hidden"
          accept={ALLOWED_EXTENSIONS.join(",")}
          onChange={pickFiles}
        />
        <Button size="sm" disabled={upload.isPending} onClick={() => fileRef.current?.click()}>
          {upload.isPending ? <Spinner /> : <Upload />} Upload files
        </Button>
        <Button variant="outline" size="sm" onClick={() => setEditor({ id: null, title: "", content: "" })}>
          <Plus /> Add text
        </Button>
        <span className="text-xs text-zinc-400">PDF, DOCX, XLSX, CSV, Markdown, text, JPG or PNG · up to 25 MB</span>
      </div>
      {uploadError && <p className="mt-2 text-xs text-red-600">{uploadError}</p>}

      {editor && (
        <form
          onSubmit={(e) => {
            e.preventDefault();
            saveText.mutate(editor);
          }}
          className="mt-4 space-y-2 rounded-lg border border-zinc-200 bg-zinc-50 p-4"
        >
          <Input
            placeholder="Title"
            value={editor.title}
            maxLength={120}
            onChange={(e) => setEditor({ ...editor, title: e.target.value })}
            required
          />
          <textarea
            className="min-h-40 w-full rounded-md border border-zinc-300 bg-white px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-zinc-900"
            placeholder="Paste or type what your agents should know…"
            value={editor.content}
            onChange={(e) => setEditor({ ...editor, content: e.target.value })}
            required
          />
          {saveText.isError && <p className="text-xs text-red-600">{errorText(saveText.error)}</p>}
          <div className="flex gap-2">
            <Button type="submit" size="sm" disabled={saveText.isPending || !editor.title.trim() || !editor.content.trim()}>
              {saveText.isPending ? <Spinner /> : editor.id ? "Save and re-index" : "Add"}
            </Button>
            <Button type="button" variant="outline" size="sm" onClick={() => setEditor(null)}>
              Cancel
            </Button>
          </div>
        </form>
      )}

      {actionError && <p className="mt-3 text-xs text-red-600">{actionError}</p>}

      {docsQuery.isLoading ? (
        <div className="flex justify-center py-8">
          <Spinner className="h-5 w-5 text-zinc-500" />
        </div>
      ) : docs.length === 0 ? (
        <p className="py-8 text-center text-sm text-zinc-400">No documents yet.</p>
      ) : (
        <ul className="mt-4 divide-y divide-zinc-100 rounded-lg border border-zinc-200">
          {docs.map((doc) => (
            <li key={doc.id} className="flex items-start gap-3 p-3">
              <FileText className="mt-0.5 h-4 w-4 shrink-0 text-zinc-400" />
              <div className="min-w-0 flex-1">
                <p className="truncate text-sm font-medium text-zinc-900">{doc.filename}</p>
                <div className="mt-0.5 flex flex-wrap items-center gap-2 text-xs text-zinc-500">
                  <StatusBadge doc={doc} />
                  {doc.status === "ready" && <span>{doc.chunk_count} chunk{doc.chunk_count === 1 ? "" : "s"}</span>}
                </div>
                {doc.error_message && (
                  <p className={cn("mt-1 text-xs", doc.status === "error" ? "text-red-600" : "text-amber-700")}>
                    {doc.error_message}
                  </p>
                )}
              </div>
              <div className="flex shrink-0 gap-1">
                {doc.editable && doc.status !== "processing" && (
                  <IconButton label="Edit" onClick={() => openText.mutate(doc)} disabled={openText.isPending}>
                    <Pencil className="h-3.5 w-3.5" />
                  </IconButton>
                )}
                <IconButton
                  label="Delete"
                  danger
                  disabled={removeDoc.isPending}
                  onClick={() => {
                    if (confirm(`Delete "${doc.filename}"?`)) removeDoc.mutate(doc);
                  }}
                >
                  <Trash2 className="h-3.5 w-3.5" />
                </IconButton>
              </div>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function StatusBadge({ doc }: { doc: KnowledgeDocument }) {
  if (doc.status === "processing") {
    return (
      <span className="inline-flex items-center gap-1 rounded-full bg-sky-50 px-2 py-0.5 font-medium text-sky-700">
        <Spinner className="h-3 w-3" /> Indexing
      </span>
    );
  }
  if (doc.status === "error") {
    return (
      <span className="inline-flex items-center gap-1 rounded-full bg-red-50 px-2 py-0.5 font-medium text-red-700">
        <AlertTriangle className="h-3 w-3" /> Failed
      </span>
    );
  }
  return (
    <span className="inline-flex items-center gap-1 rounded-full bg-emerald-50 px-2 py-0.5 font-medium text-emerald-700">
      <CheckCircle2 className="h-3 w-3" /> Ready
    </span>
  );
}

function IconButton({
  label,
  danger,
  children,
  ...props
}: React.ButtonHTMLAttributes<HTMLButtonElement> & { label: string; danger?: boolean }) {
  return (
    <button
      type="button"
      title={label}
      aria-label={label}
      className={cn(
        "rounded-md p-1.5 text-zinc-400 transition-colors cursor-pointer disabled:opacity-50",
        danger ? "hover:bg-red-50 hover:text-red-600" : "hover:bg-zinc-100 hover:text-zinc-800",
      )}
      {...props}
    >
      {children}
    </button>
  );
}

function SearchPanel({ kb, token }: { kb: KnowledgeBase; token: string }) {
  const [query, setQuery] = useState("");
  const search = useMutation<KnowledgeSearchResponse, Error, string>({
    mutationFn: (q) => knowledgeApi.search(token, kb.id, { query: q, top_k: 5 }),
  });

  return (
    <div>
      <p className="text-sm text-zinc-500">
        Ask something the way an agent would — you&apos;ll see the passages it would get back.
      </p>
      <form
        onSubmit={(e) => {
          e.preventDefault();
          if (query.trim()) search.mutate(query.trim());
        }}
        className="mt-3 flex gap-2"
      >
        <Input placeholder="e.g. What is the refund window?" value={query} onChange={(e) => setQuery(e.target.value)} />
        <Button type="submit" disabled={search.isPending || !query.trim()}>
          {search.isPending ? <Spinner /> : <Search />} Search
        </Button>
      </form>
      {search.isError && <p className="mt-2 text-xs text-red-600">{errorText(search.error)}</p>}

      {search.data &&
        (search.data.results.length === 0 ? (
          <p className="py-8 text-center text-sm text-zinc-400">
            Nothing found. Documents still indexing aren&apos;t searchable yet.
          </p>
        ) : (
          <ol className="mt-4 space-y-3">
            {search.data.results.map((hit, i) => (
              <li key={hit.id} className="rounded-lg border border-zinc-200 p-4">
                <div className="flex flex-wrap items-center gap-2 text-xs">
                  <span className="font-semibold text-zinc-900">#{i + 1}</span>
                  <span className="truncate text-zinc-600">{hit.filename}</span>
                  <span className="rounded-full bg-violet-50 px-2 py-0.5 font-medium text-violet-700">
                    {hit.retrieval_method}
                  </span>
                  <span className="ml-auto tabular-nums text-zinc-400">score {hit.score.toFixed(3)}</span>
                </div>
                <p className="mt-2 whitespace-pre-wrap text-sm leading-relaxed text-zinc-700">{hit.content}</p>
              </li>
            ))}
          </ol>
        ))}
    </div>
  );
}
