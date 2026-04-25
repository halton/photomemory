#!/usr/bin/env python3
"""
rematch_faces.py - 迭代式人脸重新匹配

策略：用已命名人物的所有已知人脸做最近邻匹配，迭代扩展参考集。
每轮匹配后将新匹配的人脸加入参考集，下一轮用更大的参考集继续匹配，
直到没有新匹配。同时支持吸收已有的未命名 person 聚类。

用法:
  python3 scripts/rematch_faces.py --db ./data/photomemory.db --dry-run
  python3 scripts/rematch_faces.py --db ./data/photomemory.db --threshold 0.50
  python3 scripts/rematch_faces.py --db ./data/photomemory.db --absorb-threshold 0.55
"""

import argparse
import sqlite3
import numpy as np
from datetime import datetime

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from backend.db_util import get_optimized_connection


def _normalize(v):
    """Normalize vectors along last axis."""
    if v.ndim == 1:
        n = np.linalg.norm(v)
        return v / n if n > 0 else v
    norms = np.linalg.norm(v, axis=1, keepdims=True)
    norms[norms == 0] = 1
    return v / norms


def rematch_faces(db_path: str, threshold: float = 0.68, dry_run: bool = False,
                  person_ids: list = None, max_rounds: int = 10,
                  absorb_threshold: float = 0.72):
    """
    迭代式人脸重新匹配。

    Phase 1: 吸收未命名 person 聚类
      - 对每个未命名 person，用其所有人脸与已命名人物做最近邻匹配
      - 若某个未命名 person 的多数人脸最近邻都属于同一个已命名 person，
        且平均最小距离 < absorb_threshold，则吸收整个聚类

    Phase 2: 迭代式单人脸匹配
      - 每轮用所有已知人脸做 KNN，将距离 < threshold 的未分配人脸收入
      - 新收入的人脸加入参考集，进入下一轮
      - 直到没有新匹配

    Args:
        db_path: 数据库路径
        threshold: 余弦距离阈值 (默认 0.50)
        dry_run: 仅报告不写入
        person_ids: 只匹配指定 person_id 列表
        max_rounds: 最大迭代轮数
        absorb_threshold: 吸收未命名聚类的阈值
    """
    conn = get_optimized_connection(db_path)
    c = conn.cursor()

    # 1. 加载已命名 persons
    if person_ids:
        placeholders = ",".join("?" * len(person_ids))
        persons = c.execute(f"""
            SELECT id, name, face_count FROM persons
            WHERE name IS NOT NULL AND id IN ({placeholders})
        """, person_ids).fetchall()
    else:
        persons = c.execute("""
            SELECT id, name, face_count FROM persons
            WHERE name IS NOT NULL
        """).fetchall()

    if not persons:
        print("❌ 没有已命名的人物，请先用 --label 命名。")
        conn.close()
        return {"matched": 0, "details": {}}

    # 2. 加载每个已命名 person 的所有已知 face embeddings
    person_map = {}  # pid -> {name, known_embs (normalized), face_count}
    for pid, name, face_count in persons:
        face_rows = c.execute(
            "SELECT embedding FROM faces WHERE person_id=? AND embedding IS NOT NULL",
            (pid,)
        ).fetchall()
        if not face_rows:
            continue
        embs = np.array([np.frombuffer(r[0], dtype=np.float32) for r in face_rows])
        embs = _normalize(embs)
        person_map[pid] = {"name": name, "known_embs": embs, "face_count": face_count}

    print(f"📋 已加载 {len(person_map)} 个已命名人物:")
    for pid, p in person_map.items():
        print(f"   {p['name']} (id={pid}, 已知 {len(p['known_embs'])} 张)")

    now = datetime.now().isoformat()
    total_matched = 0
    details = {pid: 0 for pid in person_map}

    # ── Phase 1: 吸收未命名 person 聚类 ──
    print(f"\n🔗 Phase 1: 吸收未命名聚类（阈值={absorb_threshold}）...")

    unnamed_persons = c.execute("""
        SELECT id, face_count FROM persons
        WHERE name IS NULL AND face_count >= 3
        ORDER BY face_count DESC
    """).fetchall()

    absorbed_count = 0
    for upid, ufc in unnamed_persons:
        # 加载此未命名 person 的所有人脸
        urows = c.execute(
            "SELECT id, embedding FROM faces WHERE person_id=? AND embedding IS NOT NULL",
            (upid,)
        ).fetchall()
        if not urows:
            continue
        u_face_ids = [r[0] for r in urows]
        u_embs = np.array([np.frombuffer(r[1], dtype=np.float32) for r in urows])
        u_embs = _normalize(u_embs)

        # 对每张人脸找最近的已命名 person
        best_pid_per_face = []
        best_dist_per_face = []
        for pidx, (pid, pdata) in enumerate(person_map.items()):
            known = pdata["known_embs"]
            sims = u_embs @ known.T  # [U, K]
            min_dists = 1 - sims.max(axis=1)  # [U]
            for i in range(len(u_face_ids)):
                if pidx == 0 or min_dists[i] < best_dist_per_face[i]:
                    if pidx == 0:
                        best_pid_per_face.append(pid)
                        best_dist_per_face.append(min_dists[i])
                    else:
                        best_pid_per_face[i] = pid
                        best_dist_per_face[i] = min_dists[i]

        best_dist_per_face = np.array(best_dist_per_face)

        # 检查：多数人脸是否指向同一个 person，且平均距离足够小
        from collections import Counter
        vote = Counter(best_pid_per_face)
        top_pid, top_count = vote.most_common(1)[0]
        vote_ratio = top_count / len(u_face_ids)

        # 只取投票给 top_pid 的人脸的距离
        voted_dists = [best_dist_per_face[i] for i in range(len(u_face_ids))
                       if best_pid_per_face[i] == top_pid]
        avg_dist = np.mean(voted_dists)

        if vote_ratio >= 0.6 and avg_dist < absorb_threshold:
            pname = person_map[top_pid]["name"]
            print(f"  ✅ 吸收 person#{upid} ({ufc}张) → {pname}: "
                  f"投票率={vote_ratio:.0%}, 平均距离={avg_dist:.3f}")

            if not dry_run:
                c.execute("UPDATE faces SET person_id=? WHERE person_id=?",
                          (top_pid, upid))
                c.execute("DELETE FROM persons WHERE id=?", (upid,))

            # 更新内存中的参考集（dry_run 也需要）
            person_map[top_pid]["known_embs"] = np.vstack([
                person_map[top_pid]["known_embs"], u_embs
            ])
            person_map[top_pid]["face_count"] += ufc

            absorbed_count += ufc
            details[top_pid] = details.get(top_pid, 0) + ufc
            total_matched += ufc

    print(f"  聚类吸收完成: {absorbed_count} 张人脸")

    # ── Phase 2: 迭代式单人脸匹配 ──
    print(f"\n🔄 Phase 2: 迭代匹配未分配人脸（阈值={threshold}）...")

    matched_face_ids_set = set()  # track assigned face_ids for dry_run mode

    for round_num in range(1, max_rounds + 1):
        # 加载当前未分配人脸
        rows = c.execute("""
            SELECT id, embedding FROM faces
            WHERE person_id IS NULL AND embedding IS NOT NULL
        """).fetchall()

        if not rows:
            print(f"  第 {round_num} 轮: 没有未分配人脸了。")
            break

        # In dry_run, also exclude previously matched
        if dry_run and matched_face_ids_set:
            rows = [(fid, emb) for fid, emb in rows if fid not in matched_face_ids_set]
            if not rows:
                print(f"  第 {round_num} 轮: 没有未分配人脸了。")
                break

        face_ids = np.array([r[0] for r in rows])
        embeddings = np.array([np.frombuffer(r[1], dtype=np.float32) for r in rows])
        embeddings = _normalize(embeddings)

        # 对每张未分配人脸，找最近的已命名 person（基于所有已知人脸）
        best_min_dist = np.full(len(face_ids), np.inf)
        best_person_id = np.full(len(face_ids), -1, dtype=int)

        for pid, pdata in person_map.items():
            known = pdata["known_embs"]
            # 分块计算避免内存爆炸（known 可能很大）
            chunk_size = 500
            min_dist_to_person = np.full(len(face_ids), np.inf)
            for start in range(0, len(known), chunk_size):
                chunk = known[start:start + chunk_size]
                sims = embeddings @ chunk.T
                chunk_min = 1 - sims.max(axis=1)
                min_dist_to_person = np.minimum(min_dist_to_person, chunk_min)

            better = min_dist_to_person < best_min_dist
            best_min_dist[better] = min_dist_to_person[better]
            best_person_id[better] = pid

        # 筛选通过阈值的
        mask = best_min_dist < threshold
        matched_this_round = mask.sum()

        if matched_this_round == 0:
            print(f"  第 {round_num} 轮: 无新匹配，停止迭代。")
            break

        # 按 person 分组
        round_results = {}
        for i in np.where(mask)[0]:
            pid = int(best_person_id[i])
            fid = int(face_ids[i])
            dist = float(best_min_dist[i])
            if pid not in round_results:
                round_results[pid] = []
            round_results[pid].append((fid, dist, i))

        print(f"  第 {round_num} 轮: 匹配 {matched_this_round} 张人脸")

        for pid, matches in round_results.items():
            pname = person_map[pid]["name"]
            dists = [d for _, d, _ in matches]
            print(f"    {pname}: +{len(matches)} (距离 {min(dists):.3f}~{max(dists):.3f})")

            if not dry_run:
                for fid, _, _ in matches:
                    c.execute("UPDATE faces SET person_id=? WHERE id=?", (pid, fid))

            # 将新匹配的人脸加入参考集（dry_run 也更新内存以支持迭代）
            new_indices = [idx for _, _, idx in matches]
            new_embs = embeddings[new_indices]
            person_map[pid]["known_embs"] = np.vstack([
                person_map[pid]["known_embs"], new_embs
            ])
            person_map[pid]["face_count"] += len(matches)
            # Track for dry_run exclusion
            for fid, _, _ in matches:
                matched_face_ids_set.add(fid)

            details[pid] = details.get(pid, 0) + len(matches)
            total_matched += len(matches)

        if not dry_run:
            conn.commit()

    # ── 更新 person centroids 和 face_count ──
    if not dry_run and total_matched > 0:
        for pid, pdata in person_map.items():
            centroid = pdata["known_embs"].mean(axis=0)
            centroid = _normalize(centroid)
            c.execute("""
                UPDATE persons
                SET embedding_centroid=?, face_count=?, updated_at=?
                WHERE id=?
            """, (centroid.astype(np.float32).tobytes(), pdata["face_count"], now, pid))
        conn.commit()

    conn.close()

    prefix = "[DRY RUN] " if dry_run else ""
    print(f"\n{prefix}🎯 总计匹配 {total_matched} 张人脸")
    for pid, pdata in person_map.items():
        cnt = details.get(pid, 0)
        if cnt > 0:
            print(f"   {pdata['name']}: +{cnt} (总计 {pdata['face_count']})")

    return {"matched": total_matched, "details": {str(k): v for k, v in details.items()}}


def main():
    parser = argparse.ArgumentParser(description="迭代式人脸重新匹配")
    parser.add_argument("--db", default="./data/photomemory.db", help="数据库路径")
    parser.add_argument("--threshold", type=float, default=0.68,
                        help="单脸匹配余弦距离阈值 (默认 0.68)")
    parser.add_argument("--absorb-threshold", type=float, default=0.72,
                        help="聚类吸收阈值 (默认 0.72)")
    parser.add_argument("--max-rounds", type=int, default=10,
                        help="最大迭代轮数 (默认 10)")
    parser.add_argument("--dry-run", action="store_true", help="仅预览，不写入数据库")
    parser.add_argument("--person-ids", type=int, nargs="+",
                        help="只匹配指定 person_id (默认全部已命名)")
    args = parser.parse_args()

    rematch_faces(args.db, threshold=args.threshold, dry_run=args.dry_run,
                  person_ids=args.person_ids, max_rounds=args.max_rounds,
                  absorb_threshold=args.absorb_threshold)


if __name__ == "__main__":
    main()
