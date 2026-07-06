"""AST Parser — extract code structure from Python files using ast.parse.

Extracts:
- Module docstrings
- Classes with methods and docstrings  
- Functions with signatures and docstrings
- Import relationships (internal module references)
- Convention comments (CONVENTION:, PITFALL:, NOTE:)

Design doc: docs/CONTEXT_AND_AGENT_PLATFORM_PLAN.md §10
"""

from __future__ import annotations

import ast
import hashlib
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class AstNode:
    """A single code element extracted from a Python file."""

    node_type: str  # module, class, function, method, import, convention
    name: str
    qualified_name: str  # fully qualified: module.Class.method
    file_path: str
    line_start: int
    line_end: int
    docstring: str | None = None
    signature: str | None = None  # function/method signature
    parent_name: str | None = None  # parent class or module
    body: str | None = None  # first 500 chars of body for context
    source_hash: str | None = None  # SHA of the file at parse time
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class ParseResult:
    """Result of parsing a single Python file."""

    file_path: str
    source_hash: str
    nodes: list[AstNode]
    errors: list[str] = field(default_factory=list)


def parse_file(file_path: str | Path, *, max_bytes: int = 1_000_000) -> ParseResult:
    """Parse a single Python file and extract AST nodes.

    Args:
        file_path: Path to the .py file
        max_bytes: Max file size to parse

    Returns:
        ParseResult with extracted nodes
    """
    path = Path(file_path)
    errors: list[str] = []

    try:
        source = path.read_text(encoding="utf-8", errors="replace")
    except (OSError, UnicodeDecodeError) as e:
        return ParseResult(
            file_path=str(path),
            source_hash="",
            nodes=[],
            errors=[f"read_error: {e}"],
        )

    if len(source.encode("utf-8")) > max_bytes:
        return ParseResult(
            file_path=str(path),
            source_hash="",
            nodes=[],
            errors=["file_too_large"],
        )

    source_hash = hashlib.sha256(source.encode()).hexdigest()

    try:
        tree = ast.parse(source, filename=str(path))
    except SyntaxError as e:
        return ParseResult(
            file_path=str(path),
            source_hash=source_hash,
            nodes=[],
            errors=[f"syntax_error: {e}"],
        )

    nodes: list[AstNode] = []
    walker = _AstWalker(str(path), source, source_hash)
    walker.walk(tree, nodes)

    return ParseResult(
        file_path=str(path),
        source_hash=source_hash,
        nodes=nodes,
        errors=errors,
    )


def parse_directory(
    root_path: str | Path,
    *,
    file_glob: str = "**/*.py",
    max_files: int = 500,
) -> list[ParseResult]:
    """Parse all Python files in a directory tree.

    Args:
        root_path: Root directory to walk
        file_glob: Glob pattern for files
        max_files: Max files to parse (safety limit)

    Returns:
        List of ParseResult per file
    """
    root = Path(root_path)
    results: list[ParseResult] = []

    for i, py_file in enumerate(root.glob(file_glob)):
        if i >= max_files:
            logger.warning("Max files limit reached: %d", max_files)
            break
        if py_file.is_file() and not py_file.name.startswith("."):
            result = parse_file(py_file)
            results.append(result)

    return results


class _AstWalker:
    """Internal: walks a parsed AST and collects nodes."""

    def __init__(self, file_path: str, source: str, source_hash: str):
        self.file_path = file_path
        self.source = source
        self.source_hash = source_hash
        self._source_lines = source.split("\n")
        self._module_doc: str | None = None

    def walk(self, tree: ast.AST, nodes: list[AstNode]) -> None:
        """Walk the AST and collect nodes."""
        # Module docstring
        self._module_doc = ast.get_docstring(tree)

        # Module node
        nodes.append(AstNode(
            node_type="module",
            name=Path(self.file_path).stem,
            qualified_name=Path(self.file_path).stem,
            file_path=self.file_path,
            line_start=1,
            line_end=len(self._source_lines),
            docstring=self._module_doc,
            source_hash=self.source_hash,
        ))

        # Walk top-level statements (parent_name="" for module-level)
        for node in ast.iter_child_nodes(tree):
            self._visit_node(node, nodes, parent_name="")

    def _visit_node(
        self, node: ast.AST, nodes: list[AstNode], parent_name: str = ""
    ) -> None:
        """Visit a single AST node and recurse."""
        module_stem = Path(self.file_path).stem

        # ── Class ────────────────────────────────────────────
        if isinstance(node, ast.ClassDef):
            qname = f"{parent_name}.{node.name}" if parent_name else f"{module_stem}.{node.name}"
            doc = ast.get_docstring(node)
            bases = [ast.unparse(b) for b in node.bases] if node.bases else []
            decorators = [ast.unparse(d) for d in node.decorator_list] if node.decorator_list else []

            nodes.append(AstNode(
                node_type="class",
                name=node.name,
                qualified_name=qname,
                file_path=self.file_path,
                line_start=node.lineno,
                line_end=node.end_lineno or node.lineno,
                docstring=doc,
                signature=f"class {node.name}({', '.join(bases)})" if bases else f"class {node.name}",
                parent_name=parent_name,
                body=self._get_body(node),
                source_hash=self.source_hash,
                metadata={"bases": bases, "decorators": decorators},
            ))

            # Visit class body
            for child in node.body:
                self._visit_node(child, nodes, parent_name=qname)

        # ── Function / Method ────────────────────────────────
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            qname = f"{parent_name}.{node.name}" if parent_name else f"{module_stem}.{node.name}"
            doc = ast.get_docstring(node)
            node_type = "method" if parent_name else "function"
            args = [a.arg for a in node.args.args]
            returns = ast.unparse(node.returns) if node.returns else None
            decorators = [ast.unparse(d) for d in node.decorator_list] if node.decorator_list else []

            sig_parts = [f"def {node.name}("]
            sig_parts.append(", ".join(args))
            sig_parts.append(")")
            if returns:
                sig_parts.append(f" -> {returns}")

            nodes.append(AstNode(
                node_type=node_type,
                name=node.name,
                qualified_name=qname,
                file_path=self.file_path,
                line_start=node.lineno,
                line_end=node.end_lineno or node.lineno,
                docstring=doc,
                signature="".join(sig_parts),
                parent_name=parent_name,
                body=self._get_body(node),
                source_hash=self.source_hash,
                metadata={"args": args, "returns": returns, "decorators": decorators,
                           "is_async": isinstance(node, ast.AsyncFunctionDef)},
            ))

        # ── Import ───────────────────────────────────────────
        elif isinstance(node, ast.Import):
            for alias in node.names:
                nodes.append(AstNode(
                    node_type="import",
                    name=alias.name,
                    qualified_name=alias.name,
                    file_path=self.file_path,
                    line_start=node.lineno,
                    line_end=node.end_lineno or node.lineno,
                    parent_name=parent_name,
                    source_hash=self.source_hash,
                    metadata={"alias": alias.asname},
                ))

        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            for alias in node.names:
                full = f"{module}.{alias.name}" if module else alias.name
                nodes.append(AstNode(
                    node_type="import",
                    name=full,
                    qualified_name=full,
                    file_path=self.file_path,
                    line_start=node.lineno,
                    line_end=node.end_lineno or node.lineno,
                    parent_name=parent_name,
                    source_hash=self.source_hash,
                    metadata={"module": module, "alias": alias.asname, "level": node.level},
                ))

    def _get_body(self, node: ast.AST) -> str | None:
        """Extract first ~500 chars of node body for context."""
        if not hasattr(node, "body"):
            return None
        try:
            body_text = ast.unparse(node)
            return body_text[:500] if len(body_text) > 500 else body_text
        except Exception:
            return None
