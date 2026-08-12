"""Repository-aware relevant-code retrieval.

Never assumes filenames describe their contents. Uses the traceback to find
implicated files, reads surrounding source lines, searches for symbol references
and imports, and retrieves related configs, tests, and dependency definitions.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path
from typing import Any

from app.context_builder.stack_trace_parser import StackFrame
from app.core.config import settings

_SYMBOL_REGEX = re.compile(r"([A-Za-z_][A-Za-z0-9_]*)")

_IGNORED_PARTS = {
    "__pycache__", ".git", ".venv", "venv", "node_modules", "dist", "build",
    ".pytest_cache", ".mypy_cache", "htmlcov", ".tox", ".next", ".nuxt", "target",
}
_IGNORED_SUFFIXES = {".pyc", ".pyo", ".lock", ".min.js", ".map"}


class CodeSnippet(dict):
    """A slice of source code returned to the context builder."""
    # keys: path, content, error_line, functions, imports, type


class LocalRetriever:
    def __init__(self, repo_root: Path | str | None = None) -> None:
        self.repo_root = Path(repo_root or settings.INTERNAL_REPO_ROOT).resolve()

    def set_repo_root(self, repo_root: Path | str) -> None:
        self.repo_root = Path(repo_root).resolve()

    # ------------------------------------------------------------------
    def retrieve(
        self,
        frames: list[StackFrame],
        project_profile: Any = None,
    ) -> list[CodeSnippet]:
        """Return the most relevant code snippets prioritized according to spec."""
        max_files = settings.MAX_CONTEXT_FILES
        top_k_symbols = getattr(settings, "CODE_RETRIEVAL_TOP_K", 5)
        results: list[CodeSnippet] = []
        seen: set[str] = set()

        # Priority 1: Exact stack-trace files & surrounding lines
        for frame in frames:
            rel = frame.relative_path or self._to_relative(frame.file)
            if not rel or rel in seen:
                continue
            path = self.repo_root / rel
            if not path.is_file() or self._ignored(rel):
                # Try finding by basename in repo
                cand = self._find_by_name(Path(rel).name)
                if cand:
                    path = cand
                    rel = self._to_relative(str(cand)) or rel
            if not path.is_file() or self._ignored(rel):
                continue
            seen.add(rel)
            snippet = self._read_with_context(path, rel, frame.line)
            results.append(snippet)
            if len(results) >= max_files:
                return results

        # Priority 2: Calling functions / symbol references across repository
        symbols = {
            f.function for f in frames
            if f.function and f.function not in ("<module>", "<lambda>", "<anonymous>", "<go_routine>")
        }
        for rel in self._search_symbols(symbols)[:top_k_symbols]:
            if rel in seen or len(results) >= max_files:
                continue
            path = self.repo_root / rel
            if not path.is_file() or self._ignored(rel):
                continue
            seen.add(rel)
            snippet = self._read_with_context(path, rel, error_line=None)
            results.append(snippet)
            if len(results) >= max_files:
                return results

        # Priority 3: Imported modules
        imported_files = self._find_imported_files(results)
        for rel in imported_files:
            if rel in seen or len(results) >= max_files:
                continue
            path = self.repo_root / rel
            if not path.is_file() or self._ignored(rel):
                continue
            seen.add(rel)
            snippet = self._read_with_context(path, rel, error_line=None)
            results.append(snippet)
            if len(results) >= max_files:
                return results

        # Priority 4: Related configuration files
        config_candidates = [".env.example", "config.py", "settings.py", "Dockerfile"]
        for cfg in config_candidates:
            if cfg in seen or len(results) >= max_files:
                continue
            path = self.repo_root / cfg
            if path.is_file():
                seen.add(cfg)
                snippet = self._read_with_context(path, cfg, error_line=None)
                results.append(snippet)
                if len(results) >= max_files:
                    return results

        # Priority 5: Related tests
        if frames:
            first_frame_path = frames[0].relative_path or frames[0].file
            stem = Path(first_frame_path).stem
            test_patterns = [f"test_{stem}.py", f"{stem}_test.py", f"{stem}.test.ts", f"{stem}.test.js"]
            for tp in test_patterns:
                matched = self._find_by_name(tp)
                if matched and matched.is_file():
                    rel = self._to_relative(str(matched))
                    if rel and rel not in seen:
                        seen.add(rel)
                        results.append(self._read_with_context(matched, rel, error_line=None))
                        if len(results) >= max_files:
                            return results

        # Priority 6: Dependency definitions
        dep_files = ["requirements.txt", "package.json", "pyproject.toml", "go.mod", "Cargo.toml"]
        for dep in dep_files:
            if dep in seen or len(results) >= max_files:
                continue
            path = self.repo_root / dep
            if path.is_file():
                seen.add(dep)
                snippet = self._read_with_context(path, dep, error_line=None)
                results.append(snippet)
                if len(results) >= max_files:
                    return results

        return results

    # ------------------------------------------------------------------
    def _read_with_context(
        self,
        path: Path,
        rel: str,
        error_line: int | None,
    ) -> CodeSnippet:
        window = settings.CONTEXT_LINE_WINDOW
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except Exception as exc:
            return CodeSnippet(path=rel, content=f"# unreadable: {exc}", error_line=None)

        lines = text.splitlines()
        functions = self._extract_functions(lines)
        imports = self._extract_imports(lines)

        if error_line and 1 <= error_line <= len(lines):
            start = max(0, error_line - window - 1)
            end = min(len(lines), error_line + window)
        else:
            end = min(len(lines), 60)
            start = 0
        numbered = [f"{i + 1:5d} | {lines[i]}" for i in range(start, end)]
        content = "\n".join(numbered)

        return CodeSnippet(
            path=rel,
            content=content,
            error_line=error_line,
            functions=functions,
            imports=imports,
        )

    @staticmethod
    def _extract_functions(lines: list[str]) -> list[str]:
        funcs: list[str] = []
        for line in lines:
            stripped = line.strip()
            if stripped.startswith("def ") or stripped.startswith("async def "):
                name = stripped.split("(")[0].split()[-1]
                funcs.append(name)
            elif stripped.startswith("class "):
                name = stripped.split("(")[0].split()[-1].rstrip(":")
                funcs.append(f"class {name}")
            elif stripped.startswith("function ") or stripped.startswith("const ") and "=>" in stripped:
                name = stripped.split("(")[0].split()[-1].replace("=", "").strip()
                funcs.append(name)
        return funcs

    @staticmethod
    def _extract_imports(lines: list[str]) -> list[str]:
        imports: list[str] = []
        for line in lines:
            stripped = line.strip()
            if stripped.startswith("import ") or stripped.startswith("from ") or "require(" in stripped or "import " in stripped:
                imports.append(stripped)
        return imports

    def _find_imported_files(self, snippets: list[CodeSnippet]) -> list[str]:
        found: list[str] = []
        for snip in snippets:
            for imp in snip.get("imports", []):
                # Python: from app.services.payment import ...
                m = re.search(r"from\s+([A-Za-z0-9_.]+)\s+import", imp)
                if m:
                    module_path = m.group(1).replace(".", "/")
                    for ext in [".py", "/__init__.py"]:
                        cand = self.repo_root / f"{module_path}{ext}"
                        if cand.is_file():
                            rel = self._to_relative(str(cand))
                            if rel:
                                found.append(rel)
                # JS: import ... from './payment'
                m2 = re.search(r"from\s+['\"](\.[^'\"]+)['\"]", imp)
                if m2:
                    rel_to_file = (Path(snip["path"]).parent / m2.group(1)).as_posix()
                    for ext in [".ts", ".js", ".tsx", ".jsx", "/index.ts", "/index.js"]:
                        cand = self.repo_root / f"{rel_to_file}{ext}"
                        if cand.is_file():
                            rel = self._to_relative(str(cand))
                            if rel:
                                found.append(rel)
        return found

    def _search_symbols(self, symbols: set[str]) -> list[str]:
        if not symbols:
            return []
        patterns = "|".join(re.escape(s) for s in symbols if s)
        if not patterns:
            return []
        matches: dict[str, int] = {}
        regex = re.compile(rf"\b(?:{patterns})\b")
        for ext in ("*.py", "*.ts", "*.js", "*.go", "*.rs"):
            for path in self.repo_root.rglob(ext):
                if self._ignored(str(path)):
                    continue
                try:
                    with open(path, "r", encoding="utf-8", errors="ignore") as fh:
                        for line in fh:
                            if regex.search(line):
                                rel = self._to_relative(str(path))
                                if rel:
                                    matches[rel] = matches.get(rel, 0) + 1
                except Exception:
                    continue
        return sorted(matches, key=matches.get, reverse=True)

    def _find_by_name(self, filename: str) -> Path | None:
        if not filename:
            return None
        for p in self.repo_root.rglob(filename):
            if p.is_file() and not self._ignored(str(p)):
                return p
        return None

    def _to_relative(self, file_str: str) -> str | None:
        try:
            p = Path(file_str)
            if p.is_absolute():
                return str(p.resolve().relative_to(self.repo_root)).replace("\\", "/")
            return str(p).replace("\\", "/")
        except (ValueError, OSError):
            return None

    def _ignored(self, path: str) -> bool:
        parts = set(Path(path).parts)
        if parts & _IGNORED_PARTS:
            return True
        if Path(path).suffix in _IGNORED_SUFFIXES:
            return True
        return False
