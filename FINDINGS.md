# PhotoMemory - Detailed Findings Table

## Issue Tracking Matrix

| ID | Category | Severity | Issue | Location | Impact | Fix Time |
|:--:|:--------:|:--------:|-------|----------|--------|----------|
| E1 | Architecture | 🔴 CRITICAL | Dual Framework (Flask + FastAPI) | api_server.py (1557 LOC) + api_fastapi.py (211 LOC) | Maintenance nightmare, unclear source of truth | 1-2 days |
| E2 | Error Handling | 🔴 CRITICAL | 16+ bare `except Exception:` blocks | api_server.py:581,590,601,643; thumbnail.py | Silent failures, impossible to debug production issues | 3 days |
| E3 | Video Support | 🔴 CRITICAL | No video metadata extraction | db/migrations.py (schema) | Cannot get duration, codec, bitrate; UI shows no info | 2-3 days |
| E4 | Logging | 🟠 HIGH | All errors logged with `print()` | api_server.py throughout | Production logs lost, no structured tracking | 2 days |
| E5 | Video Support | 🟠 HIGH | Fragile ffmpeg dependency | services/thumbnail.py:36-46 | Hardcoded paths, no version check, no fallback | 1 day |
| E6 | Error Handling | 🟠 HIGH | Face thumbnail crash risk | api_server.py:776-810 | JSON parsing failures unhandled, bbox bounds not checked | 2 days |
| E7 | Database | 🟠 HIGH | No database indices | api_server.py:498-507 (search) | Performance degrades >10k photos, LIKE queries slow | 1 day |
| E8 | Pagination | 🟠 HIGH | Offset-based pagination | api_server.py:429, 513 | O(n) per page, hardcoded max 200 | 2 days |
| E9 | Search | 🟠 HIGH | Incomplete Chinese support | services/geocode.py | Only 24 cities vs 334+ in China, no locale detection | 3 days |
| E10 | Search | 🟠 HIGH | Inefficient query construction | api_server.py:477-495 | Exponential OR conditions, 9 LIKE ops per search term | 2 days |
| E11 | Validation | 🟠 HIGH | No input validation | api_server.py:429 | `int()` not wrapped, ValueError unhandled | 1 day |
| E12 | Code Quality | 🟠 HIGH | Duplicate code | api_server.py:615-645 + services/thumbnail.py:48-80 | ~200 LOC duplicated, if one breaks other does too | 1 day |
| E13 | Database | 🟡 MEDIUM | No transaction rollback | api_server.py:344-359 | Commit failures not handled, data inconsistency | 1 day |
| E14 | Search | 🟡 MEDIUM | Person query hits DB per search | api_server.py:549-552 | Should cache known person names instead | 1 day |
| E15 | Video Support | 🟡 MEDIUM | No video streaming/HTTP ranges | api_server.py:686 | Large videos slow on slow networks, no resume | 3 days |
| E16 | Frontend | 🟡 MEDIUM | No video player UI | frontend/index.html | No HTML5 `<video>` element, users can't preview | 2 days |
| E17 | Security | 🟡 MEDIUM | Path traversal incomplete | api_server.py:677 | is_safe_path() function appears missing/undefined | 1 day |
| E18 | Caching | 🟡 MEDIUM | No atomic cache writes | api_server.py:599-602 | Disk full → incomplete file left on disk | 1 day |
| E19 | Search | 🟡 MEDIUM | No search query logging | api_server.py:402-545 | Can't find popular searches or debug issues | 1 day |
| E20 | Config | 🟢 LOW | No production docker-compose | docker-compose.yml | Dev-only, no production overrides | 1 day |

## By Category

### 🔴 CRITICAL (Must Fix Before Production)
- **E1**: Dual framework migration (Flask + FastAPI) - INCOMPLETE
- **E2**: 16+ bare exception blocks - SILENT FAILURES
- **E3**: Video metadata missing - UNUSABLE FOR VIDEO LIBRARY

### 🟠 HIGH (Fix This Sprint)
- **E4**: No structured logging (print() → lost)
- **E5**: ffmpeg detection too fragile
- **E6**: Face thumbnail crash risk
- **E7**: Missing database indices
- **E8**: Pagination inefficient
- **E9**: Chinese city support incomplete (24 vs 334+ cities)
- **E10**: Search query construction inefficient
- **E11**: Input validation missing
- **E12**: Duplicate code (thumbnail functions)

### 🟡 MEDIUM (Fix This Quarter)
- **E13**: No transaction rollback
- **E14**: Person query caching missing
- **E15**: No video streaming/HTTP ranges
- **E16**: No video player UI
- **E17**: Path traversal incomplete
- **E18**: Atomic write safety missing
- **E19**: Search query logging missing
- **E20**: No production docker config

---

## Code Issues by File

### backend/api_server.py (1,557 LOC - 🔴 NEEDS ATTENTION)
| Issue | Line(s) | Severity | Fix |
|-------|---------|----------|-----|
| Bare except blocks | 581-582, 590-591, 601-602, 643 | 🔴 | Add logging |
| No input validation | 429 | 🟠 | Wrap int() in try-except |
| Duplicate ffmpeg code | 615-645 | 🟠 | Use services/thumbnail.py |
| is_safe_path undefined | 677 | 🟡 | Find or implement function |
| Face JSON parsing crash | 776 | 🟠 | Add try-except |
| Face bbox bounds | 779-780 | 🟠 | Add min/max checks |
| No transaction rollback | 344-359 | 🟡 | Add try-except-rollback |
| Print logging | throughout | 🟠 | Use logging module |
| Pagination O(n) | 513-514 | 🟠 | Implement cursor pagination |
| Dynamic WHERE clause | 498-507 | 🟡 | Safer parameterization |

### backend/services/thumbnail.py (90 LOC - 🟡 PARTIAL)
| Issue | Line(s) | Severity | Fix |
|-------|---------|----------|-----|
| Hardcoded ffmpeg paths | 40-42 | 🟠 | Add PATH env var search |
| No version check | 36-46 | 🟡 | Check ffmpeg --version |
| 10s timeout | 71 | 🟡 | Increase or configurable |
| No stderr logging | 71-77 | 🟠 | Log subprocess stderr |

### backend/db (104 + 69 + 22 LOC - ✅ MOSTLY OK)
| Issue | Location | Severity | Fix |
|-------|----------|----------|-----|
| No indices | Not implemented | 🟠 | Add CREATE INDEX commands |
| Hardcoded pool size | async_connection.py:8 | 🟡 | Make configurable |

### backend/auth (64 + 58 LOC - ✅ GOOD)
| Issue | Location | Severity | Fix |
|-------|----------|----------|-----|
| Session TTL too long | api_server.py:51 | 🟡 | Change 720 hours → 24 hours |
| Rate limit per IP only | api_server.py:94-96 | 🟡 | Add per-token rate limiting |

### frontend/ (280 KB - 🔴 INCOMPLETE)
| Issue | File | Severity | Fix |
|-------|------|----------|-----|
| No video player | index.html | 🟠 | Add HTML5 `<video>` element |
| No streaming UI | admin.html | 🟠 | Add progress bars, buffering |
| Minimal components | .js files | 🟡 | Refactor to components |

### backend/services/geocode.py (34 LOC - 🟡 INCOMPLETE)
| Issue | Line(s) | Severity | Fix |
|-------|---------|----------|-----|
| Only 24 cities | 5-24 | 🟠 | Expand to 500+ cities |
| No locale detection | throughout | 🟡 | Add locale/language support |
| canonicalize_city incomplete | 26-34 | 🟡 | Implement proper function |

---

## Risk Assessment

### High-Risk Scenarios
1. **Large Video File** → 10s ffmpeg timeout → silent failure → placeholder emoji
2. **Malformed Face Data** → JSON parsing crash in face_thumbnail() → 500 error
3. **Slow Network** → Large video file download blocks request → timeout
4. **>10k Photos** → LIKE queries without indices → 5+ second response times
5. **Framework Bugfix** → Applied to Flask, forgotten in FastAPI → inconsistent behavior

### Security Vulnerabilities
- **Medium**: Path traversal via photo_id (if is_safe_path missing)
- **Low**: 30-day session TTL (excessive)
- **Low**: Rate limiting per IP only (shared networks bypass)

---

## Dependency Analysis

### External Dependencies
| Package | Version | Usage | Status |
|---------|---------|-------|--------|
| Flask | ? | Main API framework | 🟡 Deprecated (migrating) |
| FastAPI | ? | New API framework | 🟡 Incomplete |
| SQLite3 | 3.x | Database | ✅ Built-in |
| Pillow | ? | Image manipulation | ✅ Core |
| InsightFace | ? | Face recognition | ✅ Phase 2 |
| ffmpeg | system | Video thumbnails | 🟡 Fragile detection |
| aiosqlite | ? | Async DB (FastAPI) | ✅ Complete |

### Missing Dependencies
- ❌ `logging` - No structured logging (using print)
- ❌ `ffprobe` - No video metadata extraction
- ❌ `celery` - No async tasks (thumbnails block)
- ❌ `sentry` - No error tracking
- ❌ `prometheus` - No metrics

---

## Recommendations Summary

### Immediate (This Week)
1. ✅ Choose Flask OR FastAPI, delete the other
2. ✅ Fix 16 exception blocks with logging
3. ✅ Add input validation wrapper for int()
4. ✅ Create database indices

### Sprint (This Month)
5. ✅ Add video metadata extraction (ffprobe)
6. ✅ Replace print() with logging module
7. ✅ Expand CITY_ALIASES to 500+ cities
8. ✅ Implement cursor-based pagination

### Quarter (Next 3 Months)
9. ✅ Add HTTP range request support
10. ✅ Build HTML5 video player UI
11. ✅ Implement async thumbnail generation
12. ✅ Migrate to PostgreSQL (>50k photos)

