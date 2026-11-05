"""NL -> SQL agent. Uses LLM if available, else a rule-based fallback. Executes via DuckDB
against the dataset registered as table 'data'. Read-only, allowlist-enforced."""
from __future__ import annotations

import re

import duckdb
import pandas as pd

from app.services.llm_provider import get_llm_provider
from app.utils.security import validate_readonly_sql, UnsafeSQLError

# Aggregation keywords (whole words only) -> (SQL function, alias prefix).
_AGGREGATIONS = [
    (("average", "avg", "mean"), "AVG", "avg"),
    (("maximum", "max", "highest", "largest", "biggest"), "MAX", "max"),
    (("minimum", "min", "lowest", "smallest"), "MIN", "min"),
    (("sum", "total"), "SUM", "sum"),
]
_GROUP_WORDS = r"(?:by|per|for each|for every|across|grouped by)"


def _words(text: str) -> str:
    """Lowercase, turn _ and - into spaces, drop punctuation, collapse whitespace."""
    text = re.sub(r"[_\-]+", " ", str(text).lower())
    text = re.sub(r"[^a-z0-9 ]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _quote(name: str) -> str:
    return '"' + str(name).replace('"', '""') + '"'


def _find_columns(q: str, cols: list[str]) -> list[tuple[int, int, str]]:
    """Columns mentioned in q as whole words, as (start, end, column), longest names first
    so 'total charges' wins over a shorter overlapping name. Overlapping matches are dropped."""
    found: list[tuple[int, int, str]] = []
    for col in sorted(cols, key=lambda c: len(_words(c)), reverse=True):
        phrase = _words(col)
        if not phrase:
            continue
        for m in re.finditer(rf"\b{re.escape(phrase)}\b", q):
            if all(m.end() <= s or m.start() >= e for s, e, _ in found):
                found.append((m.start(), m.end(), col))
                break
    return sorted(found)


def _rule_based_sql(question: str, df: pd.DataFrame) -> str:
    """Keyword fallback used when no LLM is configured. Matches column names as whole
    words (spaces or underscores), so 'average' no longer matches a column called 'age'."""
    q = _words(question)
    cols = list(df.columns)
    numeric = [c for c in cols if pd.api.types.is_numeric_dtype(df[c]) and not pd.api.types.is_bool_dtype(df[c])]

    if re.search(r"\b(how many rows|count of rows|number of rows|row count)\b", q):
        return "SELECT COUNT(*) AS row_count FROM data"
    if re.search(r"\b(list|what|which|show)\b.*\bcolumns\b", q):
        return "SELECT * FROM data LIMIT 5"

    mentioned = _find_columns(q, cols)

    # "... by contract type" / "per region" -> GROUP BY the column right after the group word.
    # Only categorical or low-cardinality columns make sense as groups.
    group_col = None
    for start, _end, col in mentioned:
        n_unique = df[col].nunique(dropna=True)
        groupable = col not in numeric or (n_unique <= 20 and n_unique < len(df) / 2)
        if groupable and re.search(rf"\b{_GROUP_WORDS}\s*$", q[:start]):
            group_col = col
            break

    # Mask matched column names so e.g. 'total' inside 'total charges' is not read as SUM.
    masked = q
    for start, end, _ in reversed(mentioned):
        masked = masked[:start] + " " * (end - start) + masked[end:]

    agg = next(
        ((fn, alias) for words, fn, alias in _AGGREGATIONS
         if re.search(r"\b(" + "|".join(words) + r")\b", masked)),
        None,
    )
    wants_count = re.search(r"\b(how many|count|number of)\b", masked) is not None

    if "first numeric column" in q and numeric:
        metric = numeric[0]
    else:
        metric = next((c for _s, _e, c in mentioned if c in numeric and c != group_col), None)

    def _agg_expr(fn: str, col: str) -> str:
        expr = f"{fn}({_quote(col)})"
        return f"ROUND({expr}, 2)" if fn in ("AVG", "SUM") else expr

    top_n = re.search(r"\b(top|bottom|first) (\d+)\b", q)

    if group_col is not None:
        g = _quote(group_col)
        if metric and not wants_count:
            # "monthly charges by region" with no aggregation word -> total per group.
            fn, alias = agg or ("SUM", "sum")
            value = _quote(f"{alias}_{metric}")
            return (f"SELECT {g}, {_agg_expr(fn, metric)} AS {value} FROM data "
                    f"GROUP BY {g} ORDER BY {value} DESC LIMIT 50")
        return f"SELECT {g}, COUNT(*) AS count FROM data GROUP BY {g} ORDER BY count DESC LIMIT 50"

    # "top 5 customers by total charges" -> the 5 rows with the highest value.
    if top_n and metric:
        order = "ASC" if top_n.group(1) == "bottom" else "DESC"
        return f"SELECT * FROM data ORDER BY {_quote(metric)} {order} LIMIT {min(int(top_n.group(2)), 500)}"

    if agg and metric:
        fn, alias = agg
        return f"SELECT {_agg_expr(fn, metric)} AS {_quote(f'{alias}_{metric}')} FROM data"

    if wants_count and mentioned:
        col = mentioned[0][2]
        return f"SELECT {_quote(col)}, COUNT(*) AS count FROM data GROUP BY {_quote(col)} ORDER BY count DESC LIMIT 50"

    if top_n:
        return f"SELECT * FROM data LIMIT {min(int(top_n.group(2)), 500)}"
    return "SELECT * FROM data LIMIT 10"


def generate_sql(question: str, df: pd.DataFrame) -> tuple[str, str]:
    """Returns (sql, source) where source is 'llm' or 'rule_based'."""
    llm = get_llm_provider()
    schema = ", ".join(f"{c} ({df[c].dtype})" for c in df.columns)
    if llm.is_available():
        raw = llm.complete(
            system=(
                "You translate natural-language questions into a single read-only DuckDB SQL SELECT statement "
                "against a table named 'data'. Output ONLY the SQL, no explanation, no markdown fences. "
                "Never use DROP/DELETE/UPDATE/INSERT/ALTER/CREATE/TRUNCATE/ATTACH/COPY."
            ),
            prompt=f"Table 'data' columns: {schema}\nQuestion: {question}\nSQL:",
        )
        sql = raw.strip().strip("`").replace("sql\n", "").strip()
        if sql and not sql.lower().startswith("ai explanation unavailable"):
            return sql, "llm"
    return _rule_based_sql(question, df), "rule_based"


def run_sql(sql: str, df: pd.DataFrame) -> dict:
    validated = validate_readonly_sql(sql)
    # No file or network access: otherwise table functions such as
    # read_csv('/etc/passwd') would pass the keyword checks and read server files.
    con = duckdb.connect(database=":memory:", config={"enable_external_access": False})
    con.register("data", df)
    try:
        result_df = con.execute(validated).fetchdf()
    finally:
        con.close()
    return {
        "columns": list(result_df.columns.astype(str)),
        "rows": result_df.head(500).to_dict(orient="records"),
        "row_count": int(len(result_df)),
    }
