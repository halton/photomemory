# Backend Review

## Scores

| Dimension | Score | Notes |
|-----------|-------|-------|
| Security | 4/5 | LIKE injection fixed; PATCH uses parameterized queries; minor input validation gaps |
| Performance | 3/5 | Ring buffer not thread-safe; middleware always runs |
| Test Quality | 4/5 | Good coverage of happy + error paths; some assertions too lenient |
| Code Quality | 3/5 | Inconsistent connection management; f-string SQL construction pattern |

## Findings

### Security

- 🔵 **PATCH endpoint accepts arbitrary string lengths for `name`/`description`** — No length validation on input fields. A malicious client could send megabytes in `name`. Add `if len(data.get("name","")) > 255: abort(400)`.

- 🟡 **`cover_photo_id` not validated as belonging to the album** — PATCH accepts any integer for `cover_photo_id` without checking it exists or belongs to the album. Could reference photos the user shouldn't access.

- 🔵 **Perf stats endpoint leaks query parameters** — `_perf_ring` stores `request.args.get("q", "")` which could contain user search terms. The `/api/perf/stats` endpoint exposes these to any authenticated user.

- ✅ **LIKE wildcard escaping done correctly** — `safe_q` properly escapes `%` and `_` with `ESCAPE '\'`. Good fix.

- ✅ **PATCH uses parameterized queries** — No SQL injection risk; the f-string only interpolates column names from a hardcoded allowlist (`name=?`, `description=?`, `cover_photo_id=?`), not user input.

### Performance

- 🔴 **`deque` is not thread-safe for iteration** — `_perf_ring` is a `deque(maxlen=100)` shared across requests. While `deque.append` is thread-safe in CPython, iterating over it in `perf_stats` (`[e for e in _perf_ring ...]`) can raise `RuntimeError` if the deque mutates mid-iteration. Use `list(_perf_ring)` to snapshot, or add a `threading.Lock`.

- 🟡 **Middleware runs on every request including static files** — `before_request`/`after_request` hooks fire for all routes including static asset serving. Add a path filter (e.g., skip if `request.path` doesn't start with `/api/`).

- 🟡 **Health check now runs a `COUNT(*)` on photos table** — On large databases this is a full table scan. Use `SELECT 1 FROM photos LIMIT 1` instead to verify connectivity without scanning.

### Test Quality

- 🟡 **`test_city_suggestion` assertion is too loose** — `assert "city" in types or "folder" in types` will pass even if the feature is broken and returns unrelated folder matches. Test should assert on the specific expected suggestion text.

- 🟡 **`test_directory_suggestion` assumes seed data has `/test` directories** — If seed data changes, the test silently breaks. Should insert known test data or document seed data dependency.

- 🔵 **Video tests don't clean up on assertion failure before `finally`** — This is actually fine since `finally` always runs, but `_make_video_file` uses `os.getcwd()` which is fragile if tests change working directory.

- ✅ **PATCH tests cover all key paths** — rename, description, empty update (400), nonexistent (404), cover update. Good edge case coverage.

- ✅ **LIKE wildcard safety test is valuable** — `test_like_wildcards_safe` directly tests the security fix. Good practice.

### Code Quality

- 🟡 **`conn.close()` called inconsistently in PATCH handler** — If `conn.execute` on the UPDATE throws, `conn.close()` is never called. Use `try/finally` or context manager. Same pattern exists in the health check (though there `conn.close()` before return is at least present).

- 🔵 **Duplicate `safe_q` assignment** — `safe_q = q.replace(...)` is computed twice identically in `search_suggest` (lines for person and directory suggestions). Compute once before both queries.

- 🔵 **Import placement** — `from flask import g` and `from collections import deque` are at module level mid-file rather than at the top with other imports. Move to top for consistency.

## Summary

Solid feature additions. The LIKE escaping fix and parameterized PATCH queries show good security awareness. Main concerns: the ring buffer needs thread-safe iteration (🔴), connection management should use `try/finally` throughout, and the perf middleware should skip non-API routes. Tests are meaningful and cover key edge cases, though a couple of assertions could be tighter. Overall a good changeset that needs one critical fix (deque iteration) and a few quality improvements before merge.
