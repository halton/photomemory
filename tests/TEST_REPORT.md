# PhotoMemory 测试报告

- 测试总数：130
- 通过：129
- 失败：1
- 通过率：99.2%

## 失败项
- tests/test_stats.py::test_stats_massive_data
  原因：插入 50 条照片记录，统计接口返回的 'total' / 'photos' / 'count' 字段小于 50，未能如预期计数（请检查统计口径）。

## 主要说明
- 所有新增/扩充 case 均已实际生效、执行。
- 并发类测试因 sqlite DB 测试环境偶尔报 `database is locked` 警告，为底层 sqlite 局限，主干流程未受影响。
- 其余 129 项全部通过。

---

**通过 pytest -v 全量执行统计生成。**