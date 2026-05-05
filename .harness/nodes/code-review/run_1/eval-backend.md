# Code Review: recluster_faces.py + merge_persons endpoint

## scripts/recluster_faces.py

### 🔴 No transaction wrapping — partial writes on failure

The script does multiple `conn.execute()` calls between `commit()`s. If it crashes mid-way through Step 3 (e.g., after updating some faces but before updating the centroid), the DB is left in an inconsistent state with `face_count` / centroid out of sync with actual faces.

**Fix:** Wrap each logical unit (Steps 3 and 4) in explicit `BEGIN`/`COMMIT` or use `with conn:` context manager.

### 🔴 Full distance matrix materialised in memory (O(n²))

Line 92-95: `embeddings @ embeddings.T` creates an N×N float64 matrix. With 50k unassigned faces, that's ~18 GB. No guard or chunking.

**Fix:** Add a sanity check / chunked computation, or use sklearn's `NearestNeighbors` with ball-tree for cosine.

### 🟡 face_count uses cached sum instead of COUNT(*)

Line 901 in merge endpoint and line 163 in recluster: `new_count` is set from `len(face_rows)` which queries only `embedding IS NOT NULL`. If any faces lack embeddings, `face_count` will drift from reality.

**Fix:** Use `SELECT COUNT(*) FROM faces WHERE person_id=?` for the authoritative count.

### 🟡 `last_insert_rowid()` is fragile

Line 175: Separate `SELECT last_insert_rowid()` call. If `get_optimized_connection` enables WAL with shared cache or triggers fire inserts, this can return a wrong ID. Use `cursor.lastrowid` instead.

### 🔵 Connection never closed on exception

Line 67-281: If any exception is raised, `conn.close()` is never called. Use a `try/finally` or context manager.

### 🔵 `import sys, os` style

Line 21: PEP 8 prefers separate import statements.

---

## backend/api_server.py — `merge_persons()`

### 🔴 No transaction — race condition between move and delete

Lines 898-921: If a concurrent request assigns new faces to `source_id` between the `UPDATE faces` and `DELETE FROM persons`, those faces become orphaned (pointing to a deleted person). The entire merge must be atomic.

**Fix:** Wrap in a single transaction with `BEGIN IMMEDIATE`.

### 🟡 `new_count` computed from stale cached values, not actual DB

Line 901: `new_count = source["face_count"] + target["face_count"]`. If `face_count` was stale (e.g., faces were deleted concurrently), this is wrong. Should use `SELECT COUNT(*) FROM faces WHERE person_id=?` after the move.

### 🟡 `import numpy` inside request handler

Line 908-909: Importing numpy/sklearn on every merge request adds ~200ms cold-start latency per worker. Move to module-level.

### 🟡 No idempotency guard

Calling merge twice with same `source_id` after the first succeeds returns 404 (source deleted). This is acceptable but undocumented. A client retry could confuse error handling. Consider returning 200 with a "already merged" note if source doesn't exist but target does.

### 🔵 Missing input type validation

Lines 882-883: `source_id` and `target_id` are used directly from JSON without `int()` cast. If a client sends a string, the SQL may behave unexpectedly (SQLite is permissive but comparison semantics differ).

### 🔵 conn.close() not in finally block

Line 926: If centroid computation raises (e.g., corrupt embedding blob), connection leaks.

---

## Summary

| Area | Issues |
|------|--------|
| DB safety | 🔴×2 (no transactions in both files) |
| Memory | 🔴×1 (O(n²) distance matrix) |
| Correctness | 🟡×3 (stale counts, lastrowid, imports) |
| API design | 🟡×1 (idempotency) |
| Resource mgmt | 🔵×2 (connection leaks) |

---

## VERDICT: ITERATE

The transaction safety issues in both files are real data-corruption risks under concurrent access. The O(n²) memory issue will OOM on any non-trivial photo library. Fix the 🔴s and re-submit.
