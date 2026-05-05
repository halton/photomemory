#!/usr/bin/env python3
"""
recluster_faces.py - 用宽松参数对未归类人脸重新聚类

策略：
  1. DBSCAN 聚类未归类人脸（relaxed eps）
  2. 尝试将新聚类合并到已命名人物（merge-threshold）
  3. KNN rematch 剩余未归类人脸（rematch-threshold）

用法:
  python3 scripts/recluster_faces.py --db ./data/photomemory.db
  python3 scripts/recluster_faces.py --db ./data/photomemory.db --eps 0.7 --merge-threshold 0.45 --rematch-threshold 0.55
"""

import argparse
import sqlite3
import numpy as np
from datetime import datetime
from collections import Counter

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


def get_person_stats(conn):
    """Return dict of person stats."""
    rows = conn.execute("""
        SELECT p.id, p.name, p.face_count,
               (SELECT COUNT(*) FROM faces f WHERE f.person_id = p.id) as actual_count
        FROM persons p ORDER BY p.face_count DESC
    """).fetchall()
    unassigned = conn.execute(
        "SELECT COUNT(*) FROM faces WHERE person_id IS NULL"
    ).fetchone()[0]
    return rows, unassigned


def print_stats(conn, label=""):
    rows, unassigned = get_person_stats(conn)
    print(f"\n{'='*50}")
    print(f"  {label} Person Stats")
    print(f"{'='*50}")
    for r in rows:
        name = r[1] or f"(unnamed #{r[0]})"
        print(f"  {name}: {r[3]} faces")
    print(f"  未归类: {unassigned} faces")
    print(f"{'='*50}\n")
    return {r[0]: r[3] for r in rows}, unassigned


def recluster_faces(db_path: str, eps: float = 0.7,
                    merge_threshold: float = 0.45,
                    rematch_threshold: float = 0.55):

    conn = get_optimized_connection(db_path)
    conn.row_factory = sqlite3.Row

    try:
        _recluster_impl(conn, eps, merge_threshold, rematch_threshold)
    finally:
        conn.close()
        print("\n✅ 完成!")


def _recluster_impl(conn, eps, merge_threshold, rematch_threshold):
    from sklearn.cluster import DBSCAN

    # Step 1: Before stats
    before_counts, before_unassigned = print_stats(conn, "BEFORE")

    # Load unassigned faces
    rows = conn.execute("""
        SELECT id, embedding FROM faces
        WHERE person_id IS NULL AND embedding IS NOT NULL
    """).fetchall()

    if not rows:
        print("✅ 没有未归类人脸。")
        conn.close()
        return

    face_ids = np.array([r["id"] for r in rows])
    embeddings = np.array([np.frombuffer(r["embedding"], dtype=np.float32) for r in rows])
    embeddings = _normalize(embeddings)
    print(f"📊 加载 {len(face_ids)} 张未归类人脸")

    # Step 2: DBSCAN clustering
    print(f"\n🔬 Step 2: DBSCAN 聚类 (eps={eps}, min_samples=3)...")

    # Use cosine metric directly — avoids O(n²) precomputed matrix
    clustering = DBSCAN(eps=eps, min_samples=3, metric="cosine")
    labels = clustering.fit_predict(embeddings)

    n_clusters = len(set(labels)) - (1 if -1 in labels else 0)
    n_noise = (labels == -1).sum()
    print(f"  发现 {n_clusters} 个聚类, {n_noise} 个噪声点")

    # Load named persons for merge
    named_persons = conn.execute("""
        SELECT id, name, embedding_centroid, face_count FROM persons
        WHERE name IS NOT NULL AND embedding_centroid IS NOT NULL
    """).fetchall()

    person_centroids = {}
    for p in named_persons:
        centroid = np.frombuffer(p["embedding_centroid"], dtype=np.float32)
        person_centroids[p["id"]] = {
            "name": p["name"],
            "centroid": _normalize(centroid),
            "face_count": p["face_count"]
        }

    print(f"  已命名人物: {len(person_centroids)} 个")

    # Step 3: Try to merge new clusters into existing persons
    print(f"\n🔗 Step 3: 合并聚类到已命名人物 (阈值={merge_threshold})...")
    now = datetime.now().isoformat()
    merged_count = 0
    new_cluster_count = 0

    for cluster_id in range(n_clusters):
        mask = labels == cluster_id
        cluster_face_ids = face_ids[mask]
        cluster_embs = embeddings[mask]
        cluster_centroid = _normalize(cluster_embs.mean(axis=0))

        # Find closest named person
        best_pid = None
        best_dist = float("inf")
        for pid, pdata in person_centroids.items():
            dist = 1 - float(np.dot(cluster_centroid, pdata["centroid"]))
            if dist < best_dist:
                best_dist = dist
                best_pid = pid

        if best_pid and best_dist < merge_threshold:
            pname = person_centroids[best_pid]["name"]
            print(f"  ✅ 聚类 {cluster_id} ({len(cluster_face_ids)}张) → {pname} (距离={best_dist:.3f})")

            # Assign faces to person
            for fid in cluster_face_ids:
                conn.execute("UPDATE faces SET person_id=? WHERE id=?", (best_pid, int(fid)))

            # Update person centroid and count
            all_faces = conn.execute(
                "SELECT embedding FROM faces WHERE person_id=? AND embedding IS NOT NULL",
                (best_pid,)
            ).fetchall()
            new_count = conn.execute(
                "SELECT COUNT(*) FROM faces WHERE person_id=?", (best_pid,)
            ).fetchone()[0]
            all_embs = np.array([np.frombuffer(r["embedding"], dtype=np.float32) for r in all_faces])
            all_embs = _normalize(all_embs)
            new_centroid = _normalize(all_embs.mean(axis=0))

            conn.execute("""
                UPDATE persons SET face_count=?, embedding_centroid=?, updated_at=?
                WHERE id=?
            """, (new_count, new_centroid.astype(np.float32).tobytes(), now, best_pid))

            # Update in-memory centroid
            person_centroids[best_pid]["centroid"] = new_centroid
            person_centroids[best_pid]["face_count"] = new_count
            merged_count += len(cluster_face_ids)
        else:
            # Create new unnamed person for this cluster
            c = conn.execute("""
                INSERT INTO persons (name, face_count, embedding_centroid, created_at, updated_at)
                VALUES (NULL, ?, ?, ?, ?)
            """, (len(cluster_face_ids), cluster_centroid.astype(np.float32).tobytes(), now, now))
            new_pid = c.lastrowid
            for fid in cluster_face_ids:
                conn.execute("UPDATE faces SET person_id=? WHERE id=?", (new_pid, int(fid)))
            new_cluster_count += 1
            if best_pid:
                print(f"  ➕ 聚类 {cluster_id} ({len(cluster_face_ids)}张) → 新人物 #{new_pid} (最近距离={best_dist:.3f} > {merge_threshold})")
            else:
                print(f"  ➕ 聚类 {cluster_id} ({len(cluster_face_ids)}张) → 新人物 #{new_pid}")

    conn.commit()
    print(f"  合并: {merged_count} 张人脸, 新建: {new_cluster_count} 个聚类")

    # Step 4: KNN rematch for remaining unassigned
    print(f"\n🎯 Step 4: KNN rematch 剩余未归类人脸 (阈值={rematch_threshold})...")

    remaining = conn.execute("""
        SELECT id, embedding FROM faces
        WHERE person_id IS NULL AND embedding IS NOT NULL
    """).fetchall()

    if not remaining:
        print("  没有剩余未归类人脸。")
    else:
        rem_ids = np.array([r["id"] for r in remaining])
        rem_embs = np.array([np.frombuffer(r["embedding"], dtype=np.float32) for r in remaining])
        rem_embs = _normalize(rem_embs)

        # Reload named persons (may have updated centroids)
        named_persons = conn.execute("""
            SELECT id, name, embedding_centroid FROM persons
            WHERE name IS NOT NULL AND embedding_centroid IS NOT NULL
        """).fetchall()

        if named_persons:
            # Load all known face embeddings per person for KNN
            person_embs = {}
            for p in named_persons:
                pid = p["id"]
                face_rows = conn.execute(
                    "SELECT embedding FROM faces WHERE person_id=? AND embedding IS NOT NULL",
                    (pid,)
                ).fetchall()
                if face_rows:
                    embs = np.array([np.frombuffer(r["embedding"], dtype=np.float32) for r in face_rows])
                    person_embs[pid] = _normalize(embs)

            # Find best match for each remaining face
            best_dist = np.full(len(rem_ids), np.inf)
            best_pid = np.full(len(rem_ids), -1, dtype=int)

            for pid, known in person_embs.items():
                sims = rem_embs @ known.T
                min_dist = 1 - sims.max(axis=1)
                better = min_dist < best_dist
                best_dist[better] = min_dist[better]
                best_pid[better] = pid

            mask = best_dist < rematch_threshold
            rematch_count = mask.sum()

            if rematch_count > 0:
                for i in np.where(mask)[0]:
                    conn.execute("UPDATE faces SET person_id=? WHERE id=?",
                                 (int(best_pid[i]), int(rem_ids[i])))

                # Update persons
                matched_pids = set(best_pid[mask])
                for pid in matched_pids:
                    face_rows = conn.execute(
                        "SELECT embedding FROM faces WHERE person_id=? AND embedding IS NOT NULL",
                        (int(pid),)
                    ).fetchall()
                    new_count = conn.execute(
                        "SELECT COUNT(*) FROM faces WHERE person_id=?", (int(pid),)
                    ).fetchone()[0]
                    all_embs = np.array([np.frombuffer(r["embedding"], dtype=np.float32) for r in face_rows])
                    all_embs = _normalize(all_embs)
                    new_centroid = _normalize(all_embs.mean(axis=0))
                    conn.execute("""
                        UPDATE persons SET face_count=?, embedding_centroid=?, updated_at=?
                        WHERE id=?
                    """, (new_count, new_centroid.astype(np.float32).tobytes(), now, int(pid)))

                conn.commit()
                print(f"  匹配: {rematch_count} 张人脸")
            else:
                print("  无新匹配。")
        else:
            print("  没有已命名人物可匹配。")

    # Step 5: After stats with delta
    after_counts, after_unassigned = print_stats(conn, "AFTER")

    print("📈 Delta:")
    all_pids = set(list(before_counts.keys()) + list(after_counts.keys()))
    for pid in sorted(all_pids):
        before_c = before_counts.get(pid, 0)
        after_c = after_counts.get(pid, 0)
        delta = after_c - before_c
        if delta != 0:
            # Get name
            row = conn.execute("SELECT name FROM persons WHERE id=?", (pid,)).fetchone()
            name = row["name"] if row and row["name"] else f"(unnamed #{pid})"
            print(f"  {name}: {before_c} → {after_c} ({'+' if delta > 0 else ''}{delta})")

    delta_unassigned = after_unassigned - before_unassigned
    print(f"  未归类: {before_unassigned} → {after_unassigned} ({'+' if delta_unassigned > 0 else ''}{delta_unassigned})")


def main():
    parser = argparse.ArgumentParser(description="用宽松参数重新聚类未归类人脸")
    parser.add_argument("--db", default="./data/photomemory.db", help="数据库路径")
    parser.add_argument("--eps", type=float, default=0.7,
                        help="DBSCAN eps (余弦距离, 默认 0.7)")
    parser.add_argument("--merge-threshold", type=float, default=0.45,
                        help="聚类合并到已命名人物的阈值 (默认 0.45)")
    parser.add_argument("--rematch-threshold", type=float, default=0.55,
                        help="KNN rematch 阈值 (默认 0.55)")
    args = parser.parse_args()

    recluster_faces(args.db, eps=args.eps,
                    merge_threshold=args.merge_threshold,
                    rematch_threshold=args.rematch_threshold)


if __name__ == "__main__":
    main()
