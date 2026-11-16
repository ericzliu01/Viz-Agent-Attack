"""SQL ground-truth consistency checker (stage-1 guard).

The stage-1 LLM emits both an ``answer`` and a ``sql`` query over the dataset
CSV. This module executes that query **read-only** against an in-memory DuckDB
connection and confirms the executed scalar result matches the stated answer;
a mismatch drops the instance upstream.

Security: this is a guard, not a convenience. Only a single read-only
``SELECT``/``WITH`` statement is ever executed. Anything else -- a non-SELECT
first keyword, a DDL/DML/side-effecting keyword appearing as a statement, or
multiple ``;``-joined statements -- raises :class:`UnsafeSQL` *before* the
string reaches DuckDB.
"""
import re

import duckdb


class UnsafeSQL(Exception):
    """Raised when a query is not a single read-only SELECT/WITH statement."""


class UnsolvableTask(Exception):
    """Raised when the query errors, references a missing column, or does not
    return a 1x1 scalar result."""


# Keywords that must never appear as the leading keyword of a statement. These
# are DDL/DML/side-effecting operations; a read-only guard rejects them outright.
_FORBIDDEN_KEYWORDS = frozenset({
    "INSERT", "UPDATE", "DELETE", "DROP", "CREATE", "ALTER", "ATTACH",
    "DETACH", "COPY", "PRAGMA", "INSTALL", "LOAD", "EXPORT", "IMPORT",
    "SET", "RESET", "CALL", "USE", "VACUUM", "ANALYZE", "CHECKPOINT",
    "BEGIN", "COMMIT", "ROLLBACK", "TRUNCATE", "GRANT", "REVOKE",
    "REPLACE", "MERGE", "UPSERT", "DESCRIBE", "EXPLAIN", "SUMMARIZE",
})

# DuckDB file-access / external-source functions. A read-only SELECT can still
# read local files through these (e.g. SELECT read_text('/etc/hostname')), so
# they are blocked before execution. The catch-all `read_[a-z_]+` covers future
# read_* variants.
_FILE_ACCESS_FUNCS = frozenset({
    "READ_TEXT", "READ_TEXT_AUTO", "READ_CSV", "READ_CSV_AUTO", "READ_JSON",
    "READ_JSON_AUTO", "READ_NDJSON", "READ_PARQUET", "READ_BLOB",
    "PARQUET_SCAN", "JSON_SCAN", "CSV_SCAN", "GLOB",
})
_READ_FUNC_RE = re.compile(r"^READ_[A-Z_]+$")

# C-style block comments /* ... */ (non-greedy, across newlines).
_BLOCK_COMMENT_RE = re.compile(r"/\*.*?\*/", re.DOTALL)
# -- line comments through end of line.
_LINE_COMMENT_RE = re.compile(r"--[^\n]*")


def _strip_comments(query: str) -> str:
    """Remove SQL comments so they cannot smuggle extra statements or keywords."""
    without_block = _BLOCK_COMMENT_RE.sub(" ", query)
    without_line = _LINE_COMMENT_RE.sub(" ", without_block)
    return without_line


def _guard(query: str) -> str:
    """Validate that ``query`` is a single read-only statement.

    Returns the cleaned (comment-stripped, trailing-``;``-removed) query, or
    raises :class:`UnsafeSQL`.
    """
    cleaned = _strip_comments(query).strip()
    if not cleaned:
        raise UnsafeSQL("empty query")

    # A single trailing ';' is fine; strip it. Anything after a ';' (other than
    # whitespace) means a second statement -> reject.
    if ";" in cleaned:
        head, _, tail = cleaned.partition(";")
        if tail.strip():
            raise UnsafeSQL("multiple statements are not allowed")
        cleaned = head.strip()
        if not cleaned:
            raise UnsafeSQL("empty query")

    # Tokenize on word boundaries to inspect keywords.
    tokens = re.findall(r"[A-Za-z_]+", cleaned)
    if not tokens:
        raise UnsafeSQL("no SQL keyword found")

    first = tokens[0].upper()
    if first not in ("SELECT", "WITH"):
        raise UnsafeSQL(f"only SELECT/WITH queries are allowed, got {first!r}")

    upper_tokens = {t.upper() for t in tokens}
    forbidden = upper_tokens & _FORBIDDEN_KEYWORDS
    if forbidden:
        raise UnsafeSQL(
            f"forbidden keyword(s) present: {', '.join(sorted(forbidden))}"
        )

    file_access = {
        t for t in upper_tokens
        if t in _FILE_ACCESS_FUNCS or _READ_FUNC_RE.match(t)
    }
    if file_access:
        raise UnsafeSQL(
            f"file-access function(s) not allowed: {', '.join(sorted(file_access))}"
        )

    return cleaned


def run_sql(query: str, df, table: str = "data") -> str:
    """Execute a single read-only SQL statement over ``df`` and return the
    single scalar cell as a string.

    Raises :class:`UnsafeSQL` unless ``query`` is one read-only SELECT/WITH
    statement. Raises :class:`UnsolvableTask` on a SQL error, a missing column,
    or a non-scalar (not exactly 1 row x 1 column) result.
    """
    cleaned = _guard(query)

    con = duckdb.connect()
    try:
        # Engine-level defense: disable ALL file/URL access before registering
        # the frame or running the query. This blocks replacement scans
        # (SELECT * FROM '/etc/passwd'), read_* functions, st_read, httpfs,
        # COPY-to-file, etc. -- including shapes the token guard cannot see.
        # The token guard above stays as defense-in-depth for the common
        # read_* case (it yields a cleaner UnsafeSQL before execution).
        con.execute("SET enable_external_access=false")
        con.register(table, df)
        try:
            rows = con.execute(cleaned).fetchall()
        except duckdb.Error as exc:
            # Missing column, type error, parse/binder error, etc.
            raise UnsolvableTask(f"SQL execution failed: {exc}") from exc

        if len(rows) != 1 or len(rows[0]) != 1:
            raise UnsolvableTask(
                f"expected a 1x1 scalar result, got "
                f"{len(rows)} row(s) x {len(rows[0]) if rows else 0} column(s)"
            )
        return str(rows[0][0])
    finally:
        con.close()


def check_answer(answer: str, sql: str, df, answer_type: str = "free") -> bool:
    """Run ``sql`` to a scalar and compare it against the stated ``answer``.

    Comparison reuses :func:`run_attack_suite.grade`'s tolerance (numeric within
    1%, otherwise normalized string/label equality). Returns ``True`` when the
    executed result and the stated answer align.

    Propagates :class:`UnsafeSQL` / :class:`UnsolvableTask` from :func:`run_sql`.
    """
    from run_attack_suite import grade

    result = run_sql(sql, df)
    status, _ = grade(str(result), answer, answer_type)
    return status == "true"
