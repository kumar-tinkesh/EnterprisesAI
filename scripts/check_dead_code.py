#!/usr/bin/env python3
"""EnterpriseAI — Backend Dead-Code Tracer.

Single-file, stdlib-only, fully dynamic scanner. It re-discovers the whole
backend on every run, so new files/functions/deps are traced automatically
with no script edits.

What it checks
--------------
 [1]  Unused imports                    (AST, repo-wide usage graph)
 [2]  Unused functions                  (AST, cross-module)
 [3]  Unused classes                    (AST, framework-aware)
 [4]  Unused methods / attributes       (AST, attribute-access tracking)
 [5]  Unreferenced modules              (import-graph reachability)
 [6]  Dead local assignments            (per-function scope)
 [7]  Unreachable lines                 (code after return/raise/break/continue)
 [8]  Dead constant branches            (if False / while False ...)
 [9]  Commented-out code blocks         (heuristic)
 [10] Declared deps never imported      (pyproject.toml vs code)
 [11] uv.lock accounting                (installed / used / unused)
 [12] Dead .env variables               (.env vs Settings/os.getenv/compose)
 [13] Dockerfile issues                 (missing COPY sources, dead ENV)
 [14] docker-compose issues             (missing contexts, volumes, env_file,
                                         broken depends_on, undefined volumes)
 [15] Alembic trace                     (orphan migrations, multiple heads,
                                         model <-> migration schema drift)

Usage
-----
    python3 scripts/check_dead_code.py            # full report
    python3 scripts/check_dead_code.py --strict   # exit 1 on any finding
    python3 scripts/check_dead_code.py --quiet    # counts only
    python3 scripts/check_dead_code.py --path apps/auth

Exit code 0 = clean, 1 = findings (CI friendly).
"""
from __future__ import annotations

import argparse
import ast
import re
import sys
import time
import tomllib
from collections import defaultdict
from pathlib import Path

# --------------------------------------------------------------------------
# Config
# --------------------------------------------------------------------------
SKIP_DIRS = {
    ".venv", "venv", "node_modules", "__pycache__", ".git", ".next",
    ".pytest_cache", "dist", "build", ".keys", "egg-info",
}
SKIP_DIR_SUFFIXES = ("egg-info",)
FRONTEND_DIRS = {"web"}  # backend-only tracer

# Decorator attributes that make the decorated function "used" by a framework.
USED_DECOR_ATTRS = {
    "get", "post", "put", "patch", "delete", "head", "options", "api_route",
    "websocket", "on_event", "exception_handler", "middleware", "router",
    "app", "field_validator", "model_validator", "validator", "computed_field",
    "fixture", "parameterized", "extend", "callback", "trace", "route",
}
FRAMEWORK_BASES = {
    "Base", "BaseModel", "BaseSettings", "TimestampMixin", "str", "Enum",
    "IntEnum", "StrEnum", "Exception", "ValueError",
}
# Declared deps consumed dynamically (drivers/plugins/CLIs) — never imported
# directly by app code but legitimately required.
DYNAMIC_DEPS = {
    "aiosqlite", "asyncpg", "psycopg", "psycopg2", "psycopg2-binary",
    "email-validator", "cryptography", "uvicorn", "gunicorn",
    "pytest", "pytest-asyncio", "uvloop", "httptools", "watchfiles",
    "python-multipart",
}
# dep name -> import name
DEP_IMPORT_ALIASES = {
    "pyjwt": "jwt", "pydantic-settings": "pydantic_settings",
    "python-dotenv": "dotenv", "pillow": "PIL", "pyyaml": "yaml",
    "beautifulsoup4": "bs4", "scikit-learn": "sklearn",
    "python-jose": "jose", "pytest-asyncio": "pytest_asyncio",
}
# Dockerfile ENV names that are runtime plumbing, never read from Python.
DOCKER_ENV_INFRA = {
    "PATH", "PYTHONPATH", "PYTHONUNBUFFERED", "PYTHONDONTWRITEBYTECODE",
    "UV_COMPILE_BYTECODE", "UV_LINK_MODE", "UV_CACHE_DIR", "HOME", "LANG",
    "LC_ALL", "GPG_KEY", "PYTHON_VERSION", "PYTHON_SHA256",
}

# --------------------------------------------------------------------------
# Colors
# --------------------------------------------------------------------------
class C:
    enabled = sys.stdout.isatty()
    @classmethod
    def _c(cls, code: str, s: str) -> str:
        return f"\033[{code}m{s}\033[0m" if cls.enabled else s
    @classmethod
    def bold(cls, s): return cls._c("1", s)
    @classmethod
    def red(cls, s): return cls._c("91", s)
    @classmethod
    def green(cls, s): return cls._c("92", s)
    @classmethod
    def yellow(cls, s): return cls._c("93", s)
    @classmethod
    def grey(cls, s): return cls._c("90", s)
    @classmethod
    def ok(cls, s): return cls.green(s)
    @classmethod
    def warn(cls, s): return cls.yellow(s)
    @classmethod
    def bad(cls, s): return cls.red(s)


def find_py_files(root: Path) -> list[Path]:
    """Dynamically discover every backend .py file. Nothing is hard-coded."""
    out: list[Path] = []
    for path in sorted(root.rglob("*.py")):
        parts = set(path.relative_to(root).parts)
        if parts & SKIP_DIRS or parts & FRONTEND_DIRS:
            continue
        if any(p.endswith(SKIP_DIR_SUFFIXES) for p in path.parts):
            continue
        out.append(path)
    return out



# --------------------------------------------------------------------------
# Categories 1-4: unused imports / functions / classes / methods
# --------------------------------------------------------------------------
def _decorator_is_framework(deco: ast.AST) -> bool:
    """True for @router.get(...) / @field_validator / @pytest.fixture etc."""
    target = deco.func if isinstance(deco, ast.Call) else deco
    if isinstance(target, ast.Attribute):
        if target.attr in USED_DECOR_ATTRS:
            return True
        # @anything.get / @app.post — resource-style decorators
        base = target.value
        return isinstance(base, ast.Name) and base.id in {"router", "app", "api"}
    if isinstance(target, ast.Name):
        return target.id in USED_DECOR_ATTRS
    return False


def _class_is_framework(node: ast.ClassDef) -> bool:
    for base in node.bases:
        name = base.id if isinstance(base, ast.Name) else (
            base.attr if isinstance(base, ast.Attribute) else None)
        if name in FRAMEWORK_BASES:
            return True
    return False


def analyze_python_defs(files: list[Path], root: Path) -> dict:
    """Build definition/usage indexes and report unused code entities."""
    trees: dict[Path, ast.Module] = {}
    for f in files:
        try:
            trees[f] = ast.parse(f.read_text(encoding="utf-8"), filename=str(f))
        except SyntaxError as exc:
            print(C.warn(f"  ! parse error in {f}: {exc}"))

    # ---- global usage sets -------------------------------------------------
    used_names: set[str] = set()      # Name/Attribute ids loaded anywhere
    used_attrs: set[str] = set()      # .attribute accesses anywhere
    for tree in trees.values():
        for node in ast.walk(tree):
            if isinstance(node, ast.Name):
                used_names.add(node.id)
            elif isinstance(node, ast.Attribute):
                used_attrs.add(node.attr)
            elif isinstance(node, ast.Constant) and isinstance(node.value, str):
                used_names.add(node.value)  # __all__, string-referenced names

    findings: list[tuple[str, Path, int, str]] = []

    # ---- per-file walk ------------------------------------------------------
    for path, tree in trees.items():
        rel = path.relative_to(root)
        is_init = path.name == "__init__.py"
        in_tests = "tests" in rel.parts
        is_alembic = "alembic" in rel.parts

        # -- imports (category 1) --
        if not is_init:  # __init__.py imports are re-exports by convention
            local_used = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
            local_used |= {n.attr for n in ast.walk(tree)
                           if isinstance(n, ast.Attribute)}
            local_used |= {c.value for c in ast.walk(tree)
                           if isinstance(c, ast.Constant) and isinstance(c.value, str)}
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom) and node.module == "__future__":
                    continue  # compiler directive, never used by name
                bound: list[tuple[int, str]] = []
                if isinstance(node, ast.Import):
                    bound = [(node.lineno, a.asname or a.name.split(".")[0])
                             for a in node.names]
                elif isinstance(node, ast.ImportFrom) and node.names[0].name != "*":
                    bound = [(node.lineno, a.asname or a.name) for a in node.names]
                for lineno, name in bound:
                    if name not in local_used:
                        findings.append(("unused_imports", rel, lineno,
                                         f"unused import '{name}'"))

        for node in tree.body:  # module level only for funcs/classes
            # -- functions (category 2) --
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                decorated = any(_decorator_is_framework(d) for d in node.decorator_list)
                entry = (node.name == "main" or node.name.startswith("test_")
                         or (in_tests and node.name.startswith("_")))
                if not (decorated or entry
                        or node.name in used_names or node.name in used_attrs
                        or (is_alembic and node.name in {"upgrade", "downgrade"})):
                    findings.append(("unused_functions", rel, node.lineno,
                                     f"unused function '{node.name}()'"))
            # -- classes (category 3) --
            elif isinstance(node, ast.ClassDef):
                framework = _class_is_framework(node)
                if not (framework or node.name in used_names):
                    findings.append(("unused_classes", rel, node.lineno,
                                     f"unused class '{node.name}'"))
                # -- methods (category 4) --
                if framework:
                    continue  # ORM/pydantic members are framework-driven
                for sub in node.body:
                    if isinstance(sub, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        dunder = sub.name.startswith("__") and sub.name.endswith("__")
                        deco = any(_decorator_is_framework(d) for d in sub.decorator_list)
                        if not (dunder or deco or sub.name in used_attrs):
                            findings.append(
                                ("unused_methods", rel, sub.lineno,
                                 f"unused method '{node.name}.{sub.name}()'"))
    return {"trees": trees, "findings": findings, "used_names": used_names,
            "used_attrs": used_attrs}


# --------------------------------------------------------------------------
# Category 5: unreferenced modules (import-graph reachability)
# --------------------------------------------------------------------------
def _module_suffixes(path: Path, root: Path) -> set[str]:
    """All dotted names that could import this file, e.g. src.core.audit."""
    rel = path.relative_to(root).with_suffix("")
    if path.name == "__init__.py":
        rel = path.parent.relative_to(root)
    parts = list(rel.parts)
    return {".".join(parts[i:]) for i in range(len(parts))}


def analyze_unreferenced_modules(files: list[Path], trees: dict,
                                 root: Path) -> list[tuple[Path, int, str]]:
    by_suffix: dict[str, Path] = {}
    for f in files:
        for suf in _module_suffixes(f, root):
            by_suffix.setdefault(suf, f)

    edges: dict[Path, set[Path]] = defaultdict(set)

    def link(src: Path, tgt: Path) -> None:
        """Register an import edge; importing a module also executes every
        ancestor package __init__.py, so mark those reachable too."""
        if tgt == src:
            return
        edges[src].add(tgt)
        for parent in tgt.parents:
            init = parent / "__init__.py"
            if init.exists() and init != src:
                edges[src].add(init)
            if parent == root:
                break

    for path, tree in trees.items():
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    tgt = by_suffix.get(alias.name)
                    if tgt:
                        link(path, tgt)
            elif isinstance(node, ast.ImportFrom):
                if node.level:  # relative: resolve against this file's package
                    base_dir = path.parent
                    for _ in range(node.level - 1):
                        base_dir = base_dir.parent
                    for alias in node.names:
                        cand = (base_dir / node.module.replace(".", "/") / (alias.name + ".py")
                                if node.module else base_dir / f"{alias.name}.py")
                        if not cand.exists():
                            sub_pkg = (base_dir / node.module.replace(".", "/") / alias.name
                                       if node.module else base_dir / alias.name)
                            cand = sub_pkg / "__init__.py"
                        if node.module and not cand.exists():
                            cand = base_dir / (node.module.replace(".", "/") + ".py")
                        if cand.exists():
                            link(path, cand)
                else:
                    tgt = by_suffix.get(node.module)
                    if tgt:
                        link(path, tgt)
                    for alias in node.names:  # from pkg import submodule
                        tgt2 = by_suffix.get(f"{node.module}.{alias.name}")
                        if tgt2:
                            link(path, tgt2)

    # Entry points: launchers, alembic env/versions, tests, __main__ scripts.
    roots: set[Path] = set()
    for f in files:
        rel = f.relative_to(root)
        if (f.name in {"main.py", "api.py", "env.py", "conftest.py"}
                or "tests" in rel.parts or "alembic" in rel.parts
                or f.stem == "__main__"
                or 'if __name__ == "__main__"' in f.read_text(errors="ignore")):
            roots.add(f)

    seen: set[Path] = set()
    stack = list(roots)
    while stack:
        cur = stack.pop()
        if cur in seen:
            continue
        seen.add(cur)
        stack.extend(edges.get(cur, ()))

    return [(f, 0, "module never imported by any entry point")
            for f in sorted(set(files) - seen)]


# --------------------------------------------------------------------------
# Categories 6-9: dead assigns, unreachable lines, dead branches, comments
# --------------------------------------------------------------------------
_TERMINALS = (ast.Return, ast.Raise, ast.Break, ast.Continue)


def analyze_lines(trees: dict, root: Path) -> list[tuple[str, Path, int, str]]:
    findings: list[tuple[str, Path, int, str]] = []

    for path, tree in trees.items():
        rel = path.relative_to(root)
        src_lines = path.read_text(errors="ignore").splitlines()

        for node in ast.walk(tree):
            # -- 7: unreachable statements after return/raise/break/continue --
            if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef,
                                 ast.If, ast.For, ast.While, ast.With, ast.Try,
                                 ast.AsyncFor, ast.AsyncWith)):
                stmt_lists = [val for _name, val in ast.iter_fields(node)
                              if isinstance(val, list) and val
                              and isinstance(val[0], ast.stmt)]
                for block in stmt_lists:
                    after_terminal = False
                    for stmt in block:
                        if after_terminal and not isinstance(stmt, _TERMINALS):
                            findings.append(("unreachable_lines", rel, stmt.lineno,
                                             "unreachable statement (after "
                                             "return/raise/break/continue)"))
                        if isinstance(stmt, _TERMINALS):
                            after_terminal = True

            # -- 6: dead local assignments --
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                loaded = {n.id for n in ast.walk(node)
                          if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load)}
                stored: dict[str, int] = {}
                for sub in ast.walk(node):
                    if isinstance(sub, ast.Assign):
                        for t in sub.targets:
                            if isinstance(t, ast.Name) and not t.id.startswith("_"):
                                stored.setdefault(t.id, sub.lineno)
                    elif (isinstance(sub, ast.AnnAssign) and sub.value
                          and isinstance(sub.target, ast.Name)
                          and not sub.target.id.startswith("_")):
                        stored.setdefault(sub.target.id, sub.lineno)
                for name, lineno in sorted(stored.items(), key=lambda x: x[1]):
                    if name not in loaded:
                        findings.append(("dead_assigns", rel, lineno,
                                         f"local '{name}' assigned but never used"))

            # -- 8: dead constant branches --
            if isinstance(node, ast.If) and isinstance(node.test, ast.Constant):
                val = node.test.value
                if val is False or val == 0 or val is None:
                    line = node.body[0].lineno if node.body else node.lineno
                    findings.append(("dead_branches", rel, line,
                                     "branch 'if <constant false>' never runs"))
                elif val is True and node.orelse:
                    findings.append(("dead_branches", rel, node.orelse[0].lineno,
                                     "else-branch of 'if <constant true>' never runs"))
            elif (isinstance(node, ast.While) and isinstance(node.test, ast.Constant)
                  and (node.test.value is False or node.test.value == 0)):
                findings.append(("dead_branches", rel, node.lineno,
                                 "'while <constant false>' loop never runs"))

        # -- 9: commented-out code blocks --
        codeish = re.compile(
            r"^\s*(def |class |return\b|import\s|from\s+\S+\s+import|if\s|for\s|while\s|"
            r"print\(|@\w+|self\.|assert\s|raise\s|\w+\s*=\s*\S)")
        run: list[int] = []
        for i, line in enumerate(src_lines, 1):
            stripped = line.strip()
            body = stripped.lstrip("#").strip() if stripped.startswith("#") else ""
            is_codeish = (stripped.startswith("#") and not stripped.startswith("#!")
                          and body and codeish.match(body))
            if is_codeish:
                run.append(i)
            else:
                if len(run) >= 3:
                    findings.append(("commented_code", rel, run[0],
                                     f"commented-out code block (lines {run[0]}-{run[-1]})"))
                run = []
        if len(run) >= 3:
            findings.append(("commented_code", rel, run[0],
                             f"commented-out code block (lines {run[0]}-{run[-1]})"))
    return findings


# --------------------------------------------------------------------------
# Categories 10-11: dependencies & uv.lock accounting
# --------------------------------------------------------------------------
def _dep_import_name(dep: str) -> str:
    base = re.split(r"[;\[><=!]", dep.strip())[0].strip().strip('"\'')
    return DEP_IMPORT_ALIASES.get(base.lower(), base.replace("-", "_"))


def analyze_deps(root: Path, import_roots: set[str]) -> dict:
    res: dict = {"declared": [], "unused_declared": [], "dynamic": [],
                 "installed": 0, "used_locked": 0, "unused_locked": [],
                 "drift": []}
    pyproject = root / "pyproject.toml"
    lock = root / "uv.lock"
    if not pyproject.exists():
        return res

    with open(pyproject, "rb") as fh:
        data = tomllib.load(fh)
    project_name = str(data.get("project", {}).get("name", "")).lower()
    declared = [re.split(r"[;\[><=!]", d)[0].strip()
                for d in data.get("project", {}).get("dependencies", [])]
    for deps in data.get("dependency-groups", {}).values():
        declared += [re.split(r"[;\[><=!]", d)[0].strip() for d in deps]
    res["declared"] = declared

    # declared but never imported
    for dep in declared:
        imp = _dep_import_name(dep)
        if imp in import_roots:
            continue
        if dep.lower() in DYNAMIC_DEPS:
            res["dynamic"].append(dep)
        else:
            res["unused_declared"].append(dep)

    # ---- uv.lock ----
    if not lock.exists():
        return res
    with open(lock, "rb") as fh:
        lockdata = tomllib.load(fh)
    packages: dict[str, list[str]] = {}
    for pkg in lockdata.get("package", []):
        packages[pkg["name"]] = [d["name"] for d in pkg.get("dependencies", [])]
    res["installed"] = len(packages)

    declared_lower = {d.lower(): d for d in declared}
    used_dep_names = {d.lower() for d in declared
                      if _dep_import_name(d) in import_roots}
    used_dep_names |= {d.lower() for d in DYNAMIC_DEPS if d in declared_lower}

    # subtrees reachable from used declared deps
    needed: set[str] = set()
    stack = [d for d in used_dep_names if d in packages]
    while stack:
        cur = stack.pop()
        if cur in needed:
            continue
        needed.add(cur)
        stack.extend(packages.get(cur, []))

    locked_names = set(packages) - {project_name}
    # extras of declared deps (e.g. uvicorn[standard], pwdlib[argon2]) land in
    # the lockfile without dependency links — treat them as legitimately used.
    extras = {"argon2-cffi", "argon2-cffi-bindings", "uvloop", "httptools",
              "watchfiles", "websockets", "pyyaml", "python-multipart",
              "colorama", "win32-setctime"}
    res["used_locked"] = len((needed | extras) & locked_names)
    res["unused_locked"] = sorted(locked_names - needed - extras)
    # drift: declared dep missing from lockfile
    for d in declared_lower:
        if d not in locked_names:
            res["drift"].append(f"{declared_lower[d]}: declared but not in uv.lock")
    return res


# --------------------------------------------------------------------------
# Category 12: dead .env variables
# --------------------------------------------------------------------------
def collect_env_reads(root: Path, trees: dict) -> set[str]:
    """Every env var name the project can read: Settings fields, os.getenv,
    os.environ, compose environment keys and ${VAR} interpolations."""
    reads: set[str] = set()
    for tree in trees.values():
        for node in ast.walk(tree):
            if (isinstance(node, ast.Call) and node.args
                    and isinstance(node.args[0], ast.Constant)
                    and isinstance(node.args[0].value, str)):
                fname = None
                if isinstance(node.func, ast.Name) and node.func.id == "getenv":
                    fname = "getenv"
                elif (isinstance(node.func, ast.Attribute)
                      and node.func.attr in {"get", "getenv"}
                      and isinstance(node.func.value, ast.Name)
                      and node.func.value.id in {"os", "environ"}):
                    fname = "envget"
                if fname:
                    reads.add(node.args[0].value.upper())
            elif (isinstance(node, ast.Subscript)
                  and isinstance(node.value, ast.Attribute)
                  and node.value.attr == "environ"
                  and isinstance(node.slice, ast.Constant)
                  and isinstance(node.slice.value, str)):
                reads.add(node.slice.value.upper())
        # pydantic-settings field names (any framework-based class)
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef) and _class_is_framework(node):
                for stmt in node.body:
                    if isinstance(stmt, ast.AnnAssign) and \
                            isinstance(stmt.target, ast.Name):
                        reads.add(stmt.target.id.upper())

    # compose files: environment keys + ${VAR} refs
    for cf in list(root.glob("docker-compose.y*ml")) + \
            list(root.glob("**/*compose*.y*ml")):
        if "node_modules" in str(cf):
            continue
        text = cf.read_text(errors="ignore")
        reads.update(m.upper() for m in re.findall(r"\$\{(\w+)", text))
        in_env = False
        for line in text.splitlines():
            if re.match(r"^\s+environment:\s*$", line):
                in_env = True
                continue
            if in_env:
                if line.startswith(" ") and not line.startswith("      ") and re.match(r"^\s{2,4}[\w-]+:\s*", line):
                    in_env = False
                elif line and not line.startswith(" "):
                    in_env = False
                elif re.match(r"^\s{4,6}[\w-]+:", line):
                    reads.add(line.split(":")[0].strip().upper())
    return reads


def analyze_env(root: Path, env_reads: set[str]) -> dict:
    res: dict = {"dead_vars": []}
    env_files = [root / ".env"] + [p for p in sorted(root.glob("apps/**/.env"))]
    for env_file in env_files:
        if not env_file.exists():
            continue
        for line_no, raw_line in enumerate(env_file.read_text(errors="ignore").splitlines(), start=1):
            line = raw_line.strip()
            if line and not line.startswith("#") and "=" in line:
                key = line.split("=", 1)[0].strip()
                if key.upper() not in env_reads:
                    res["dead_vars"].append(
                        (env_file.relative_to(root), line_no,
                         f"'{key}' defined but never read by code/compose"))
    return res


# --------------------------------------------------------------------------
# Categories 13-14: Dockerfile & docker-compose
# --------------------------------------------------------------------------
def analyze_dockerfiles(root: Path, env_reads: set[str]) -> list:
    issues: list = []
    seen: set[Path] = set()
    candidates = sorted(root.glob("docker/Dockerfile*")) + \
        sorted(p for p in root.glob("**/Dockerfile*")
               if "node_modules" not in p.parts and ".venv" not in p.parts)
    for dockerfile in candidates:
        if dockerfile in seen:
            continue
        if "web" in dockerfile.relative_to(root).parts:
            continue  # backend-only tracer
        seen.add(dockerfile)
        rel = dockerfile.relative_to(root)
        # A Dockerfile may be built with different contexts (repo root, its
        # own dir, its parent) — a source is only "missing" if it exists in
        # none of the plausible contexts.
        contexts = [root, dockerfile.parent, dockerfile.parent.parent]
        for i, line in enumerate(dockerfile.read_text(errors="ignore").splitlines(), 1):
            code = line.split("#")[0].strip()
            m = re.match(r"^(?:COPY|ADD)\s+(.*)$", code)
            if m and "--from=" not in m.group(1):
                parts = [p for p in m.group(1).split() if not p.startswith("--")]
                for src in parts[:-1] if len(parts) > 1 else parts:
                    if src.startswith(("/", '"')) or any(ch in src for ch in "*?["):
                        continue
                    if not any((ctx / src).exists() for ctx in contexts):
                        issues.append((rel, i,
                                       f"COPY/ADD source '{src}' does not exist"))
            m = re.match(r"^ENV\s+([A-Za-z_]\w*)[=\s]", code)
            if m:
                name = m.group(1).upper()
                if name not in DOCKER_ENV_INFRA and name not in env_reads:
                    issues.append((rel, i, f"ENV '{m.group(1)}' set but never "
                                           f"read by code/compose"))
    return issues


def analyze_compose(root: Path) -> list:
    """Structural integrity check for docker-compose files (regex-based —
    no YAML dependency). Detects missing contexts/dockerfiles/volumes,
    broken depends_on and undefined named volumes."""
    issues: list = []
    seen_compose: set[Path] = set()
    compose_files = sorted(root.glob("docker-compose.y*ml")) + \
        sorted(p for p in root.glob("**/docker-compose.y*ml")
               if "node_modules" not in p.parts) + \
        sorted(root.glob("compose.y*ml"))
    for compose in compose_files:
        if compose in seen_compose:
            continue
        seen_compose.add(compose)
        rel = compose.relative_to(root)
        base = compose.parent
        lines = compose.read_text(errors="ignore").splitlines()

        services: set[str] = set()
        defined_volumes: set[str] = set()
        section = None
        for line in lines:
            if re.match(r"^\S", line):
                top = line.split(":")[0].strip()
                section = {"services": "services",
                           "volumes": "volumes"}.get(top)
                continue
            m = re.match(r"^  ([\w-]+):\s*(?:#.*)?$", line)
            if m and section == "services":
                services.add(m.group(1))
            elif m and section == "volumes":
                defined_volumes.add(m.group(1))

        in_depends = False
        in_volumes_list = False
        cur_ctx: Path | None = None
        for i, line in enumerate(lines, 1):
            indented = line.startswith((" ", "\t"))
            if not indented:
                in_depends = in_volumes_list = False
                cur_ctx = None
                continue
            m = re.match(r"^\s+context:\s*(\S+)", line)
            if m:
                ctx = m.group(1).strip("'\"")
                cand = (base / ctx)
                cur_ctx = cand if cand.exists() else None
                if not cur_ctx:
                    issues.append((rel, i, f"build context '{ctx}' does not exist"))
                continue
            m = re.match(r"^\s+dockerfile:\s*(\S+)", line)
            if m:
                df = m.group(1).strip("'\"")
                bases = [b for b in (base, cur_ctx, root) if b]
                if not any((b / df).exists() for b in bases):
                    issues.append((rel, i, f"dockerfile '{df}' does not exist"))
                continue
            m = re.match(r"^\s+env_file:\s*(\S+)", line)
            if m:
                ef = m.group(1).strip("'\"")
                if not ((base / ef).exists() or (root / ef).exists()):
                    issues.append((rel, i, f"env_file '{ef}' does not exist"))
            if re.match(r"^\s+depends_on:\s*(#.*)?$", line):
                in_depends = True
                continue
            if re.match(r"^\s+volumes:\s*(#.*)?$", line):
                in_volumes_list = True
                continue
            if in_depends:
                m = re.match(r"^\s{6}([\w-]+):\s*$", line) or \
                    re.match(r"^\s+-\s+([\w-]+)\s*(?:#.*)?$", line)
                if m:
                    if m.group(1) not in services:
                        issues.append((rel, i, f"depends_on references unknown "
                                               f"service '{m.group(1)}'"))
                    continue
                if line.strip() and not line.strip().startswith(("-", "#")) \
                        and "condition" not in line:
                    in_depends = False
            elif in_volumes_list:
                m = re.match(r"^\s+-\s+(\S+):(\S+)\s*(?:#.*)?$", line)
                if m:
                    host = m.group(1).strip("'\"")
                    if host.startswith(("./", "../", "/")) or host == ".":
                        if not ((base / host).exists() or (root / host).exists()):
                            issues.append((rel, i, f"bind-mount source '{host}' "
                                                   f"does not exist"))
                    elif re.match(r"^[\w-]+$", host) and not host.startswith("$") \
                            and host not in defined_volumes:
                        issues.append((rel, i, f"named volume '{host}' not "
                                               f"defined in top-level volumes:"))
    return issues


# --------------------------------------------------------------------------
# Category 15: Alembic — orphans, heads, model <-> migration drift
# --------------------------------------------------------------------------
def _column_name(call: ast.Call) -> str | None:
    """First positional arg of sa.Column('name', ...) if constant."""
    if isinstance(call, ast.Call) and call.args and \
            isinstance(call.args[0], ast.Constant):
        return str(call.args[0].value)
    return None


def _module_column_lists(tree: ast.Module) -> dict[str, set[str]]:
    """Module-level lists of sa.Column(...) — used via *splats in migrations."""
    consts: dict[str, set[str]] = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and node.targets and \
                isinstance(node.targets[0], ast.Name) and \
                isinstance(node.value, ast.List):
            names = {c for c in (_column_name(e) for e in node.value.elts) if c}
            if names:
                consts[node.targets[0].id] = names
    return consts


def _migration_ops(tree: ast.Module) -> list[tuple]:
    """Extract ordered schema mutations from upgrade() of a version file."""
    flat: list[tuple] = []
    consts = _module_column_lists(tree)
    upgrade = None
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == "upgrade":
            upgrade = node
            break
    if upgrade is None:
        return flat

    for node in ast.walk(upgrade):
        if not isinstance(node, ast.Call) or \
                not isinstance(node.func, ast.Attribute):
            continue
        call = node.func.attr
        args = node.args
        if call == "create_table" and args and \
                isinstance(args[0], ast.Constant):
            cols = {c for c in (_column_name(a) for a in args[1:]) if c}
            if not cols:  # resolve splats like op.create_table('t', *_COLS)
                for a in args[1:]:
                    if isinstance(a, ast.Starred) and \
                            isinstance(a.value, ast.Name):
                        cols |= consts.get(a.value.id, set())
            flat.append(("create_table", str(args[0].value),
                         cols if cols else None))
        elif call == "drop_table" and args and \
                isinstance(args[0], ast.Constant):
            flat.append(("drop_table", str(args[0].value), None))
        elif call == "add_column" and len(args) >= 2 and \
                isinstance(args[0], ast.Constant):
            name = _column_name(args[1])
            if name:
                flat.append(("add_column", str(args[0].value), name))
        elif call == "drop_column" and len(args) >= 2 and \
                all(isinstance(a, ast.Constant) for a in args[:2]):
            flat.append(("drop_column", str(args[0].value), str(args[1].value)))
        elif call == "rename_table" and len(args) >= 2:
            flat.append(("rename_table", str(args[0].value), str(args[1].value)))
    # batch_alter_table('t') context blocks inside upgrade()
    for node in ast.walk(upgrade):
        if not isinstance(node, ast.With):
            continue
        for item in node.items:
            ctx = item.context_expr
            if isinstance(ctx, ast.Call) and \
                    isinstance(ctx.func, ast.Attribute) and \
                    ctx.func.attr == "batch_alter_table" and ctx.args and \
                    isinstance(ctx.args[0], ast.Constant):
                table = str(ctx.args[0].value)
                for sub in ast.walk(node):
                    if isinstance(sub, ast.Call) and \
                            isinstance(sub.func, ast.Attribute):
                        if sub.func.attr == "drop_column" and sub.args and \
                                isinstance(sub.args[0], ast.Constant):
                            flat.append(("drop_column", table,
                                         str(sub.args[0].value)))
                        elif sub.func.attr == "add_column" and sub.args:
                            name = _column_name(sub.args[0])
                            if name:
                                flat.append(("add_column", table, name))
    return flat


def analyze_alembic(root: Path, trees: dict) -> dict:
    res: dict = {"migrations": 0, "head": None, "orphans": [],
                 "multi_heads": [], "drift": []}
    versions_dir = None
    for f in trees:
        if f.parent.name == "versions" and "alembic" in f.parts:
            versions_dir = f.parent
            break
    if not versions_dir:
        return res

    chain: dict[str, dict] = {}
    for f in sorted(versions_dir.glob("*.py")):
        try:
            tree = ast.parse(f.read_text(encoding="utf-8"))
        except SyntaxError:
            continue
        rev = down = None
        for node in tree.body:
            if isinstance(node, ast.Assign) and node.targets and \
                    isinstance(node.targets[0], ast.Name):
                tgt = node.targets[0].id
                if tgt == "revision" and isinstance(node.value, ast.Constant):
                    rev = str(node.value.value)
                elif tgt == "down_revision":
                    if isinstance(node.value, ast.Constant):
                        down = (str(node.value.value)
                                if node.value.value is not None else None)
                    elif isinstance(node.value, ast.Name) and node.value.id == "None":
                        down = None
        if rev:
            chain[rev] = {"file": f, "down": down, "ops": _migration_ops(tree)}
    res["migrations"] = len(chain)
    if not chain:
        return res

    downs = {v["down"] for v in chain.values() if v["down"] is not None}
    for rev, meta in chain.items():
        if meta["down"] is not None and meta["down"] not in chain:
            res["orphans"].append((meta["file"].relative_to(root), 0,
                                   f"orphan migration '{rev}' (down_revision "
                                   f"'{meta['down']}' not found)"))
    heads = [r for r in chain if r not in downs]
    if len(heads) > 1:
        res["multi_heads"] = heads
    res["head"] = heads[0] if len(heads) == 1 else heads

    # ---- replay chain to compute final schema ----
    order: list[str] = []
    seen: set[str] = set()

    def walk(rev: str | None) -> None:
        if rev is None or rev in seen or rev not in chain:
            return
        walk(chain[rev]["down"])
        seen.add(rev)
        order.append(rev)

    for r in chain:
        walk(r)

    schema: dict[str, set[str] | None] = {}
    for rev in order:
        for kind, table, col in chain[rev]["ops"]:
            if kind == "create_table":
                schema[table] = set(col) if col is not None else None
            elif kind == "drop_table":
                schema.pop(table, None)
            elif kind == "add_column" and schema.get(table) is not None:
                schema.setdefault(table, set()).add(col)
            elif kind == "drop_column" and schema.get(table) is not None:
                schema.get(table, set()).discard(col)
            elif kind == "rename_table":
                if table in schema:
                    schema[col] = schema.pop(table)

    # ---- model columns (with mixin inheritance) ----
    mixins: dict[str, set[str]] = {}
    models: dict[str, set[str]] = {}
    for tree in trees.values():
        for node in tree.body:
            if not isinstance(node, ast.ClassDef):
                continue
            base_names = {b.id for b in node.bases if isinstance(b, ast.Name)}
            cols = set()
            has_tablename = False
            tname = None
            for stmt in node.body:
                if isinstance(stmt, ast.AnnAssign) and \
                        isinstance(stmt.target, ast.Name):
                    val = stmt.value
                    if isinstance(val, ast.Call) and (
                            (isinstance(val.func, ast.Attribute)
                             and val.func.attr == "mapped_column")
                            or (isinstance(val.func, ast.Name)
                                and val.func.id == "mapped_column")):
                        name = str(val.args[0].value) if val.args and \
                            isinstance(val.args[0], ast.Constant) else \
                            stmt.target.id
                        cols.add(name)
                elif isinstance(stmt, ast.Assign) and stmt.targets and \
                        isinstance(stmt.targets[0], ast.Name) and \
                        stmt.targets[0].id == "__tablename__" and \
                        isinstance(stmt.value, ast.Constant):
                    has_tablename = True
                    tname = str(stmt.value.value)
            if has_tablename and tname:
                for b in base_names:
                    cols |= mixins.get(b, set())
                models[tname] = cols
            elif cols:
                mixins[node.name] = cols

    # ---- drift ----
    fake = root / "models"
    for tname, cols in models.items():
        if tname not in schema:
            res["drift"].append((fake, 0,
                                 f"model table '{tname}' has no migration"))
            continue
        if schema[tname] is None:
            continue  # migration builds columns dynamically — skip comparison
        for col in sorted(cols - schema[tname]):
            res["drift"].append((fake, 0, f"model column '{tname}.{col}' is "
                                          f"never created by any migration"))
        for col in sorted(schema[tname] - cols):
            res["drift"].append((fake, 0, f"migration-only column "
                                          f"'{tname}.{col}' missing from models"))
    return res


# --------------------------------------------------------------------------
# Report
# --------------------------------------------------------------------------
CATEGORIES = [
    ("unused_imports", "UNUSED IMPORTS"),
    ("unused_functions", "UNUSED FUNCTIONS"),
    ("unused_classes", "UNUSED CLASSES"),
    ("unused_methods", "UNUSED METHODS/ATTRIBUTES"),
    ("unreferenced_modules", "UNREFERENCED MODULES"),
    ("dead_assigns", "DEAD LOCAL ASSIGNMENTS"),
    ("unreachable_lines", "UNREACHABLE LINES"),
    ("dead_branches", "DEAD CONSTANT BRANCHES"),
    ("commented_code", "COMMENTED-OUT CODE BLOCKS"),
    ("unused_deps", "DECLARED DEPS NEVER IMPORTED"),
    ("unused_locked", "UV.LOCK PACKAGES UNREACHABLE"),
    ("dead_env", "DEAD .ENV VARIABLES"),
    ("docker", "DOCKERFILE ISSUES"),
    ("compose", "DOCKER-COMPOSE ISSUES"),
    ("alembic", "ALEMBIC ORPHANS / DRIFT"),
]


def _print_group(idx: int, title: str, items: list, quiet: bool) -> None:
    if not items:
        if not quiet:
            print(f" [{idx:>2}] {title:<32} {C.ok('0  ✓')}")
        return
    print(f" [{idx:>2}] {title:<32} {C.bad(f'{len(items)}  ✗')}")
    if quiet:
        return
    for item in items[:40]:
        if isinstance(item, tuple) and len(item) == 3:  # (rel, lineno, msg)
            rel, lineno, msg = item
            loc = f"{rel}:{lineno}" if lineno else str(rel)
            print(C.grey(f"        {loc:<58} ") + msg)
        else:
            print(f"        {item}")
    if len(items) > 40:
        print(C.grey(f"        ... and {len(items) - 40} more"))


def main() -> int:
    ap = argparse.ArgumentParser(description="Backend dead-code tracer")
    ap.add_argument("--root", default=str(Path(__file__).resolve().parent.parent))
    ap.add_argument("--path", default=None,
                    help="only scan files under this subdirectory")
    ap.add_argument("--quiet", action="store_true", help="counts only")
    ap.add_argument("--no-color", action="store_true")
    args = ap.parse_args()
    if args.no_color or not sys.stdout.isatty():
        C.enabled = False

    root = Path(args.root).resolve()
    t0 = time.time()
    files = find_py_files(root)
    if args.path:
        sub = str((root / args.path).resolve())
        files = [f for f in files if str(f).startswith(sub)]

    trees: dict[Path, ast.Module] = {}
    for f in files:
        try:
            trees[f] = ast.parse(f.read_text(encoding="utf-8"), filename=str(f))
        except SyntaxError as exc:
            print(C.warn(f"  ! parse error in {f.relative_to(root)}: {exc}"))
    total_lines = sum(len(f.read_text(errors="ignore").splitlines()) for f in files)

    # import roots for dependency analysis
    import_roots: set[str] = set()
    for tree in trees.values():
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for a in node.names:
                    import_roots.add(a.name.split(".")[0])
            elif isinstance(node, ast.ImportFrom) and not node.level and node.module:
                import_roots.add(node.module.split(".")[0])

    defs = analyze_python_defs(files, root)
    findings: dict[str, list] = defaultdict(list)
    for key, rel, lineno, msg in defs["findings"]:
        findings[key].append((rel, lineno, msg))

    for f, lineno, msg in analyze_unreferenced_modules(files, trees, root):
        findings["unreferenced_modules"].append((f.relative_to(root), lineno, msg))

    for key, rel, lineno, msg in analyze_lines(trees, root):
        findings[key].append((rel, lineno, msg))

    deps = analyze_deps(root, import_roots)
    for dep in deps["unused_declared"]:
        findings["unused_deps"].append(
            (f"pyproject.toml dependency '{dep}' is never imported",))
    for pkg in deps["unused_locked"]:
        findings["unused_locked"].append(
            (f"'{pkg}' locked in uv.lock but unreachable from any used dep",))

    env_reads = collect_env_reads(root, trees)
    for rel, ln, msg in analyze_env(root, env_reads)["dead_vars"]:
        findings["dead_env"].append((rel, ln, msg))

    for rel, i, msg in analyze_dockerfiles(root, env_reads):
        findings["docker"].append((rel, i, msg))
    for rel, i, msg in analyze_compose(root):
        findings["compose"].append((rel, i, msg))

    alembic = analyze_alembic(root, trees)
    for rel, i, msg in alembic["orphans"] + alembic["drift"]:
        findings["alembic"].append((rel, i, msg))
    for rev in alembic["multi_heads"]:
        findings["alembic"].append((f"multiple heads: {rev}",))

    # ---------------- print ----------------
    apps = sorted({"/".join(p.relative_to(root).parts[:2])
                   for p in files if len(p.relative_to(root).parts) > 1})
    print(C.bold("\n══════════ BACKEND DEAD CODE REPORT ══════════"))
    print(C.grey(f" Scanned: {len(files)} files · {total_lines:,} lines "
                 f"in {', '.join(apps) or 'repo'}"))
    lock_path = root / "uv.lock"
    if not args.path and lock_path.exists():
        print(C.grey(f" uv.lock: {deps['installed']} installed · "
                     f"{deps['used_locked']} used · "
                     f"{len(deps['unused_locked'])} unreachable"))
        if alembic["migrations"]:
            head = alembic["head"]
            head_s = head if isinstance(head, str) else ",".join(head or [])
            print(C.grey(f" Alembic: {alembic['migrations']} migrations · "
                         f"head={head_s or 'none'}"))
    print(C.grey("──────────────────────────────────────────────"))

    total = 0
    for i, (key, title) in enumerate(CATEGORIES, 1):
        items = findings.get(key, [])
        total += len(items)
        _print_group(i, title, items, args.quiet)

    print(C.grey("──────────────────────────────────────────────"))
    if total == 0:
        print(f" RESULT: {C.ok('0 findings — backend is clean ✓')}")
    else:
        print(f" RESULT: {C.bad(f'{total} findings')} — see details above")
    print(C.grey(f" Completed in {time.time() - t0:.2f}s\n"))
    return 1 if total else 0


if __name__ == "__main__":
    sys.exit(main())










