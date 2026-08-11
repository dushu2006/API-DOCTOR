"""Relevant-code retrieval.

Never assumes filenames describe their contents. It uses the traceback to find
the implicated files, reads the surrounding source lines, then searches for
references to the failing symbols and their imports/dependencies across the
repository. Semantic retrieval is layered on top when an embedding model is
available (see :mod:`app.code_retrieval.semantic_retriever`).
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path
from typing import Any

from app.context_builder.stack_trace_parser import StackFrame
from app.core.config import settings

_SYMBOL_REGEX = re.compile(r"([A-Za-z_][A-Za-z0-9_]*)")

# Files/folders that are never useful context.
_IGNORED_PARTS = {
    "__pycache__", ".git", ".venv", "venv", "node_modules", "dist", "build",
    ".pytest_cache", ".mypy_cache", "htmlcov", ".tox",
}
_IGNORED_SUFFIXES = {".pyc", ".pyo", ".lock", ".min.js", ".map"}


class CodeSnippet(dict):
    """A slice of source code returned to the context builder."""

    # keys: path, content, error_line, functions, imports, related


class LocalRetriever:
    def __init__(self, repo_root: Path | str | None = None) -> None:
        self.repo_root = Path(repo_root or settings.REPO_ROOT).resolve()

    # ------------------------------------------------------------------
    def retrieve(self, frames: list[StackFrame]) -> list[CodeSnippet]:
        """Return the most relevant code snippets for the given frames."""
        max_files = settings.MAX_CONTEXT_FILES
        top_k_symbols = getattr(settings, "CODE_RETRIEVAL_TOP_K", 5)
        results: list[CodeSnippet] = []
        seen: set[str] = set()

        # 1 + 2. Traceback locations with surrounding lines.
        for frame in frames:
            rel = frame.relative_path or self._to_relative(frame.file)
            if not rel or rel in seen:
                continue
            path = self.repo_root / rel
            if not path.is_file() or self._ignored(rel):
                continue
            seen.add(rel)
            snippet = self._read_with_context(path, rel, frame.line)
            results.append(snippet)
            if len(results) >= max_files:
                return results

        # 3. Symbol references & imports for the failing symbols.
        symbols = {f.function for f in frames if f.function and f.function not in ("<module>", "<lambda>")}
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
                break
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

        if error_line:
            start = max(0, error_line - window - 1)
            end = min(len(lines), error_line + window)
        else:
            # For symbol-search hits without a known error line, do NOT dump
            # whole file. Keep small cap (60 lines) to save tokens.
            end = min(len(lines), 60)
            start = 0
        numbered = [f"{i + 1:5d} | {lines[i]}" for i in range(start, end)]
        content = "\n".join(numbered)
        # Attach the error caret if we have a line within range.
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
        return funcs

    @staticmethod
    def _extract_imports(lines: list[str]) -> list[str]:
        imports: list[str] = []
        for line in lines:
            stripped = line.strip()
            if stripped.startswith("import ") or stripped.startswith("from "):
                imports.append(stripped)
        return imports

    # ------------------------------------------------------------------
    def _search_symbols(self, symbols: set[str]) -> list[str]:
        """Grep the repo for references to the given symbols."""
        if not symbols:
            return []
        patterns = "|".join(re.escape(s) for s in symbols if s)
        if not patterns:
            return []
        # Fast pure-python walk (avoids relying on ripgrep/grep availability).
        matches: dict[str, int] = {}
        regex = re.compile(rf"\b(?:{patterns})\b")
        for path in self.repo_root.rglob("*.py"):
            if self._ignored(str(path)):
                continue
            try:
                with open(path, "r", encoding="utf-8", errors="ignore") as fh:
                    for line_no, line in enumerate(fh, 1):
                        if regex.search(line):
                            rel = self._to_relative(str(path))
                            if rel:
                                matches[rel] = matches.get(rel, 0) + 1
            except Exception:
                continue
        return sorted(matches, key=matches.get, reverse=True)

    # ------------------------------------------------------------------
    def _to_relative(self, file_str: str) -> str | None:
        try:
            p = Path(file_str)
            if p.is_absolute():
                return str(p.resolve().relative_to(self.repo_root))
            return str(p)
        except (ValueError, OSError):
            return None

    @staticmethod
    def _ignored(path: str) -> bool:
        parts = set(Path(path).parts)
        if parts & _IGNORED_PARTS:
            return True
        if Path(path).suffix in _IGNORED_SUFFIXES:
            return True
        return False


def _git_relative(repo_root: Path, file_str: str) -> str | None:
    try:
        return str(Path(file_str).resolve().relative_to(repo_root))
    except (ValueError, OSError):
        return None


# Re-exported helper used by the semantic retriever.
def run_git(repo_root: Path, args: list[str], timeout: int = 5) -> str:
    try:
        result = subprocess.run(
            ["git", "-C", str(repo_root), *args],
            capture_output=True, text=True, timeout=timeout,
        )
        return result.stdout.strip()
    except Exception:
        return ""
