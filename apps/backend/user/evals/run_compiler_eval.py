"""Measure how accurately the AI Compiler picks tools and fills their arguments.

    uv run python apps/backend/user/evals/run_compiler_eval.py              # retrieval only
    uv run python apps/backend/user/evals/run_compiler_eval.py --stage both # + planner (needs an LLM key)
    uv run python apps/backend/user/evals/run_compiler_eval.py --tag hinglish --json report.json

It loads ``catalog.json`` (11 realistic MCP servers) into a throwaway SQLite
database — never your real one — and runs every case in ``cases.jsonl``
through the compiler's own code:

* **retrieval** — ``catalog_engine.get_relevant_tools_semantic`` (what
  "Compile" shows). Is the expected tool ranked 1st (hit@1), in the top 3,
  in the top 8 the planner is handed? Plus MRR. Negative cases are skipped.
* **plan** — ``tool_call_planner.plan_tool_call`` (what "Run" shows). Did the
  LLM pick the expected tool, and do the arguments contain the values the
  query spelled out? Negative cases pass only if no tool is chosen.
* **pick** — ``builder.assist.tools.pick_tool`` (how the workflow builder
  binds a tool step to a tool): hybrid-search shortlist, then the model's
  pick. Did it pick the expected tool? Negative cases pass if it picks none.

Retrieval quality depends on whether an embedding provider is configured
(LLM gateway env vars): with one it's the full hybrid search (vectors + BM25
+ reranker); without, BM25 + reranker only. The report says which ran, so
two numbers are only comparable in the same mode. Embeddings are cached in
``.cache/`` next to this file, so re-runs don't pay for them again.

Case format (one JSON object per line):
    {"id", "query", "expect": {"server", "tool"} | null, "also_ok": [...],
     "args": {"<param>": <expected>}, "tags": [...]}
An expected string must appear (case-insensitive) in the value the planner
filled; a number must be equal.
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import sys
import tempfile
import time
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
EVAL_USER_ID = "eval-user"
EVAL_TENANT_ID = "eval-tenant"
LLM_UNAVAILABLE = "Chat LLM unavailable right now."


def _bootstrap(db_path: Path) -> None:
    # Must run before anything imports src.* (settings read DATABASE_URL once).
    os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{db_path}"
    for p in (ROOT, ROOT / "apps" / "auth", ROOT / "apps" / "backend"):
        if str(p) not in sys.path:
            sys.path.insert(0, str(p))


@dataclass
class CaseResult:
    id: str
    query: str
    tags: list[str]
    expected: list[tuple[str, str]]
    ranked: list[tuple[str, str]] = field(default_factory=list)
    rank: int | None = None
    plan: tuple[str, str] | None = None
    plan_message: str | None = None
    plan_ok: bool | None = None
    args_ok: bool | None = None
    picked: tuple[str, str] | None = None
    pick_ok: bool | None = None
    arg_misses: list[str] = field(default_factory=list)


# ── Embedding cache ──────────────────────────────────────────────────────────


class EmbeddingCache:
    def __init__(self, path: Path, provider: str | None):
        self.path = path
        self.provider = provider or "default"
        self.data: dict = json.loads(path.read_text()) if path.exists() else {}
        self.calls = 0
        self.hits = 0

    def _key(self, text: str) -> str:
        return hashlib.sha256(f"{self.provider}\x00{text}".encode()).hexdigest()

    async def embed(self, text: str, provider: str | None = None, model: str | None = None):
        from vendor.services.embedding import embed_text as real_embed_text

        key = self._key(text)
        if key in self.data:
            self.hits += 1
            vector, used_model = self.data[key]
            return vector, used_model
        self.calls += 1
        result = await real_embed_text(text, provider=provider or (None if self.provider == "default" else self.provider), model=model)
        if result is not None:
            self.data[key] = [result[0], result[1]]
        return result

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self.data))


# ── Setup ────────────────────────────────────────────────────────────────────


async def _seed(catalog: dict, cache: EmbeddingCache | None):
    from src.db.base import Base
    from src.db.session import SessionLocal, engine
    from src.models import Tenant
    from vendor.models import MCPTool, VendorMCPServer
    from vendor.services.text_repr import server_text, tool_text

    import vendor.models  # noqa: F401  (register tables)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with SessionLocal() as db:
        db.add(Tenant(id=EVAL_TENANT_ID, name="Eval", slug="eval"))
        for spec in catalog["servers"]:
            slug = spec["name"].lower().replace(" ", "-")
            server = VendorMCPServer(
                name=spec["name"],
                description=spec["description"],
                is_global=True,
                status="VERIFIED",
                transport="streamable_http",
                server_url=f"https://{slug}.example/mcp",
                auth_config={},
                bound_tools=[t["name"] for t in spec["tools"]],
            )
            db.add(server)
            await db.flush()
            if cache:
                embedded = await cache.embed(server_text(server))
                if embedded:
                    server.embedding, server.embedding_model, server.dim = embedded[0], embedded[1], len(embedded[0])
            for t in spec["tools"]:
                tool = MCPTool(
                    mcp_server_id=server.id,
                    name=t["name"],
                    description=t["description"],
                    input_schema=t.get("input_schema"),
                )
                if cache:
                    embedded = await cache.embed(tool_text(tool))
                    if embedded:
                        tool.embedding, tool.embedding_model, tool.dim = embedded[0], embedded[1], len(embedded[0])
                db.add(tool)
        await db.commit()


async def _embeddings_available(provider: str | None) -> bool:
    from vendor.services.embedding import embed_text

    return await embed_text("probe", provider=provider) is not None


# ── Scoring ──────────────────────────────────────────────────────────────────


def _arg_matches(expected, actual) -> bool:
    if actual is None:
        return False
    if isinstance(expected, bool):
        return expected is True
    if isinstance(expected, (int, float)):
        try:
            return float(actual) == float(expected)
        except (TypeError, ValueError):
            return False
    haystack = json.dumps(actual, ensure_ascii=False).lower() if not isinstance(actual, str) else actual.lower()
    return str(expected).lower() in haystack


async def run(args: argparse.Namespace) -> dict:
    from src.api.deps import CurrentUser
    from src.core.roles import Roles
    from src.db.session import SessionLocal, engine
    from user.services import catalog_engine
    from user.services.catalog_engine import get_relevant_tools_semantic

    catalog = json.loads(Path(args.catalog).read_text())
    cases = [json.loads(line) for line in Path(args.cases).read_text().splitlines() if line.strip()]
    if args.tag:
        cases = [c for c in cases if args.tag in c.get("tags", [])]
    if args.limit:
        cases = cases[: args.limit]

    use_vectors = not args.no_embeddings and await _embeddings_available(args.embedding_provider)
    cache = EmbeddingCache(HERE / ".cache" / "embeddings.json", args.embedding_provider) if use_vectors else None
    if cache:
        # Queries go through the same cache as the catalog.
        catalog_engine.embed_text = cache.embed
    else:
        async def no_embedding(*_a, **_k):
            return None

        catalog_engine.embed_text = no_embedding
    await _seed(catalog, cache)

    user = CurrentUser(id=EVAL_USER_ID, email="eval@example.com", full_name="Eval", role=Roles.TENANT_USER, tenant_id=EVAL_TENANT_ID)
    results: list[CaseResult] = []
    started = time.monotonic()
    async with SessionLocal() as db:
        for case in cases:
            expected = [(case["expect"]["server"], case["expect"]["tool"])] if case.get("expect") else []
            expected += [(a["server"], a["tool"]) for a in case.get("also_ok", [])]
            r = CaseResult(id=case["id"], query=case["query"], tags=case.get("tags", []), expected=expected)
            if expected:
                matches = await get_relevant_tools_semantic(
                    db, user=user, query=case["query"], top_k_servers=args.top_k_servers, top_k_tools=args.top_k_tools
                )
                r.ranked = [(s.name, t.name) for s, t, _ in matches]
                r.rank = next((i + 1 for i, pair in enumerate(r.ranked) if pair in expected), None)
            results.append(r)

    planner_status = "not run"
    if args.stage in ("plan", "both", "all"):
        planner_status = await _run_planner(args, cases, results, user)
    picker_status = "not run"
    if args.stage in ("pick", "all"):
        picker_status = await _run_picker(results, user)

    if cache:
        cache.save()
    await engine.dispose()
    return _report(args, results, use_vectors, planner_status, picker_status, time.monotonic() - started, cache)


async def _run_planner(args, cases, results: list[CaseResult], user) -> str:
    from src.db.session import SessionLocal
    from user.services.tool_call_planner import plan_tool_call
    from vendor.models import VendorMCPServer
    from vendor.services import mcp_auth
    from sqlalchemy import select

    async with SessionLocal() as db:
        # The planner refuses tools of servers the user hasn't connected.
        for server_id in (await db.execute(select(VendorMCPServer.id))).scalars():
            await mcp_auth.store_server_credentials(db, server_id=server_id, credentials={}, tenant_id=EVAL_TENANT_ID, user_id=EVAL_USER_ID)
        await db.commit()

        by_id = {c["id"]: c for c in cases}
        for r in results:
            case = by_id[r.id]
            outcome = await plan_tool_call(db, user=user, query=r.query, top_k_servers=args.top_k_servers, top_k_tools=args.top_k_tools)
            if outcome.message == LLM_UNAVAILABLE:
                for other in results:
                    other.plan_ok = other.args_ok = None
                return "skipped — no chat LLM configured for the gateway"
            r.plan_message = outcome.message
            if outcome.plan is None:
                r.plan_ok = not r.expected
                continue
            r.plan = (outcome.plan.server_name, outcome.plan.tool_name)
            r.plan_ok = r.plan in r.expected
            expected_args = case.get("args") or {}
            if r.plan_ok and expected_args:
                r.arg_misses = [
                    f"{k}: wanted {v!r}, got {outcome.plan.arguments.get(k)!r}"
                    for k, v in expected_args.items()
                    if not _arg_matches(v, outcome.plan.arguments.get(k))
                ]
                r.args_ok = not r.arg_misses
    return "ran"


async def _run_picker(results: list[CaseResult], user) -> str:
    from src.db.session import SessionLocal
    from builder.assist.llm import AssistUnavailable, Usage
    from builder.assist.tools import pick_tool

    usage = Usage()
    async with SessionLocal() as db:
        for r in results:
            try:
                candidate = await pick_tool(db, user, r.query, "", usage)
            except AssistUnavailable:
                for other in results:
                    other.pick_ok = None
                return "skipped — no chat LLM configured for the gateway"
            r.picked = (candidate.server_name, candidate.tool_name) if candidate else None
            r.pick_ok = (r.picked in r.expected) if r.expected else r.picked is None
    return f"ran ({usage.prompt_tokens + usage.completion_tokens} tokens)"


# ── Report ───────────────────────────────────────────────────────────────────


def _metrics(rs: list[CaseResult], top_k: int) -> dict:
    positives = [r for r in rs if r.expected]
    m: dict = {"cases": len(rs)}
    if positives:
        n = len(positives)
        m["hit@1"] = sum(r.rank == 1 for r in positives) / n
        m["hit@3"] = sum(r.rank is not None and r.rank <= 3 for r in positives) / n
        m[f"hit@{top_k}"] = sum(r.rank is not None for r in positives) / n
        m["mrr"] = sum(1 / r.rank for r in positives if r.rank) / n
    planned = [r for r in rs if r.plan_ok is not None]
    if planned:
        m["plan_tool_acc"] = sum(r.plan_ok for r in planned) / len(planned)
        with_args = [r for r in planned if r.args_ok is not None]
        if with_args:
            m["plan_args_acc"] = sum(r.args_ok for r in with_args) / len(with_args)
    picked = [r for r in rs if r.pick_ok is not None]
    if picked:
        m["pick_acc"] = sum(r.pick_ok for r in picked) / len(picked)
    return m


def _report(args, results, use_vectors, planner_status, picker_status, seconds, cache) -> dict:
    top_k = args.top_k_tools
    by_tag: dict[str, list[CaseResult]] = defaultdict(list)
    for r in results:
        for t in r.tags:
            by_tag[t].append(r)
    report = {
        "retrieval_mode": "hybrid (vectors + BM25 + reranker)" if use_vectors else "lexical (BM25 + reranker) — no embedding provider",
        "planner": planner_status,
        "picker": picker_status,
        "top_k_servers": args.top_k_servers,
        "top_k_tools": top_k,
        "overall": _metrics(results, top_k),
        "by_tag": {t: _metrics(rs, top_k) for t, rs in sorted(by_tag.items())},
        "seconds": round(seconds, 1),
        "embedding_calls": cache.calls if cache else 0,
        "failures": [
            {
                "id": r.id,
                "query": r.query,
                "expected": [f"{s}.{t}" for s, t in r.expected] or "no tool",
                "retrieved_top3": [f"{s}.{t}" for s, t in r.ranked[:3]],
                "rank": r.rank,
                "planned": f"{r.plan[0]}.{r.plan[1]}" if r.plan else r.plan_message,
                "arg_misses": r.arg_misses,
                "picked": f"{r.picked[0]}.{r.picked[1]}" if r.picked else None,
            }
            for r in results
            if (r.expected and r.rank != 1) or r.plan_ok is False or r.args_ok is False or r.pick_ok is False
        ],
    }
    return report


def _print(report: dict) -> None:
    def fmt(m: dict) -> str:
        keys = [k for k in m if k != "cases"]
        return f"{m['cases']:>3}  " + "  ".join(f"{k} {m[k] * 100:5.1f}%" if k != "mrr" else f"mrr {m[k]:.3f}" for k in keys)

    print(f"\nRetrieval: {report['retrieval_mode']}")
    print(f"Planner:   {report['planner']}")
    print(f"Picker:    {report['picker']}")
    print(f"\n{'overall':<12}{fmt(report['overall'])}")
    for tag, m in report["by_tag"].items():
        print(f"{tag:<12}{fmt(m)}")
    if report["failures"]:
        print(f"\nMisses ({len(report['failures'])}):")
        for f in report["failures"]:
            line = f"  [{f['id']}] rank={f['rank']} expected={f['expected']} got={f['retrieved_top3']}"
            if f["planned"] or f["arg_misses"]:
                line += f" planned={f['planned']}"
            print(line)
            for miss in f["arg_misses"]:
                print(f"      {miss}")
    print(f"\n{report['seconds']}s, {report['embedding_calls']} new embedding calls")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--stage", choices=("retrieval", "plan", "both", "pick", "all"), default="retrieval",
                        help="both = retrieval + plan; all = retrieval + plan + pick")
    parser.add_argument("--catalog", default=str(HERE / "catalog.json"))
    parser.add_argument("--cases", default=str(HERE / "cases.jsonl"))
    parser.add_argument("--tag", help="only cases with this tag (en, hinglish, typo, lookalike, paraphrase, negative)")
    parser.add_argument("--limit", type=int)
    parser.add_argument("--top-k-servers", type=int, default=5)
    parser.add_argument("--top-k-tools", type=int, default=8)
    parser.add_argument("--embedding-provider")
    parser.add_argument("--no-embeddings", action="store_true", help="force lexical-only retrieval")
    parser.add_argument("--json", help="also write the full report here")
    parser.add_argument("--min-hit1", type=float, help="exit 1 if overall hit@1 is below this (0-1), for CI")
    args = parser.parse_args(argv)

    with tempfile.TemporaryDirectory(prefix="compiler-eval-") as tmp:
        _bootstrap(Path(tmp) / "eval.db")
        report = asyncio.run(run(args))
    _print(report)
    if args.json:
        Path(args.json).write_text(json.dumps(report, indent=2, ensure_ascii=False))
    if args.min_hit1 is not None and report["overall"].get("hit@1", 0) < args.min_hit1:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
