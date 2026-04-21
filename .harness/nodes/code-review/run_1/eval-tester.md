# Test Quality Review

## Scores

| Dimension | Score | Notes |
|---|---|---|
| Coverage Breadth | 3/5 | Good happy-path coverage; missing auth, concurrency, and error-body assertions |
| Assertion Quality | 2/5 | Too many permissive status-code sets; few response-body checks |
| Edge Cases | 3/5 | SQL-injection wildcards tested; missing large input, special chars, boundary sizes |
| Isolation | 4/5 | Function-scoped fixtures; video tests use temp files with cleanup |

## Findings

### test_suggest.py

- 🔵 `test_city_suggestion` — `assert "city" in types or "folder" in types` is too loose; if the feature is city suggestion it should assert `"city"` specifically, otherwise the test passes even when the feature is broken.
- 🟡 `test_like_wildcards_safe` — only asserts status 200, never checks the response body. A 200 with an error payload would pass silently. Should assert `suggestions` is a list.
- 🟡 Missing: no test for very long query strings (e.g. 10k chars), unicode edge cases (emoji, ZWJ sequences), or `q` param missing entirely (vs empty).
- 🔵 `test_max_10_suggestions` — good limit check but doesn't seed enough data to actually trigger the cap; the assert may be vacuously true.

### test_video.py

- 🔴 `test_non_video_file_returns_400` — asserts `r.status_code in (400, 403, 404)`. Three acceptable codes means the test can't catch regressions; if behavior changes from 400 to 404 it still passes. Pin to the expected code.
- 🟡 `_make_video_file` uses `os.getcwd()` which couples test to runner working directory. If pytest is invoked from a different directory, `is_safe_path` may reject or accept unexpectedly.
- 🟡 Missing: no test for path-traversal attempts (`../../etc/passwd`), invalid Range header format (`Range: bytes=abc-def`), or HEAD request on video endpoint.
- 🟡 `test_video_valid_returns_200` — asserts `'video' in r.content_type` but doesn't verify body length equals the file size (4096 bytes). A truncated response would pass.

### test_albums.py (PATCH additions)

- 🔴 `test_update_album_rename` — asserts `r.get_json()["ok"] is True` but never verifies the name actually changed (e.g. GET the album back and check name). This tests the endpoint's response format, not the actual behavior.
- 🟡 `test_update_album_description` — only checks status 200; no body assertion at all.
- 🟡 `test_update_album_cover` — same: no verification that cover_photo_id persisted.
- 🟡 Missing: no test for duplicate name, name with special characters/empty string, excessively long name, or updating with invalid `cover_photo_id` (nonexistent photo).
- 🔵 `test_set_album_cover` still uses the old pattern of overly permissive status codes (`200, 201, 204, 400, 404, 405`). This asserts almost nothing.

### conftest.py

- 🟡 `AdminClient.get/post/delete/patch` — `kw.setdefault('headers', {}).update(self._headers)` has a subtle bug: if the caller passes `headers=` it merges, but `setdefault` returns the existing dict only if the key exists. When `headers` is already in `kw`, `setdefault` returns it; when not, it inserts `{}` and returns the new empty dict — this works, but if a caller passes `headers=None` it will fail with `AttributeError`. Minor but worth noting.
- 🔵 Seeded data has only 5 photos — insufficient to exercise pagination or the 10-suggestion cap.

## Summary

Tests cover the main happy paths for suggest, video, and album-PATCH endpoints, and test isolation is solid thanks to function-scoped temp databases. However, **assertion quality is the weakest area**: many tests accept wide ranges of status codes or only check status without verifying response bodies, meaning regressions in actual behavior would go undetected. The two critical findings are (1) video tests with overly permissive status assertions and (2) album PATCH tests that never verify mutations persisted. Edge-case coverage is decent for SQL injection but missing for input-size boundaries and malformed requests.
