#!/usr/bin/env python3
"""
PhotoMemory - Phase 2: 人脸检测 + Embedding + 聚类 + 人物标签
用法:
  python3 phase2_faces.py --db ./photomemory.db --detect   # 检测所有图片人脸
  python3 phase2_faces.py --db ./photomemory.db --cluster  # 聚类成人物
  python3 phase2_faces.py --db ./photomemory.db --label    # 交互式贴标签
  python3 phase2_faces.py --db ./photomemory.db --stats    # 统计
"""

import os
import sys
# 支持 HEIC 文件
try:
    import pillow_heif
    pillow_heif.register_heif_opener()
except ImportError:
    print("缺少 pillow-heif, 无法处理 HEIC, 运行: pip3 install pillow-heif")
    # 不退出, 仅打印警告

import json
import argparse
import sqlite3
import numpy as np
from pathlib import Path
from datetime import datetime

try:
    import insightface
    from insightface.app import FaceAnalysis
except ImportError:
    print("缺少依赖，请运行: pip3 install insightface onnxruntime")
    sys.exit(1)

try:
    from sklearn.cluster import DBSCAN
    from sklearn.preprocessing import normalize
except ImportError:
    print("缺少依赖，请运行: pip3 install scikit-learn")
    sys.exit(1)

try:
    from PIL import Image
    import cv2
except ImportError:
    print("缺少依赖，请运行: pip3 install Pillow opencv-python-headless")
    sys.exit(1)


# ── DB初始化 ──────────────────────────────────────────────

def init_face_tables(conn: sqlite3.Connection):
    c = conn.cursor()
    c.executescript("""
        CREATE TABLE IF NOT EXISTS faces (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            photo_id    INTEGER NOT NULL,
            photo_path  TEXT NOT NULL,
            bbox        TEXT,       -- JSON [x1,y1,x2,y2]
            landmark    TEXT,       -- JSON
            det_score   REAL,
            embedding   BLOB,       -- numpy float32 bytes
            person_id   INTEGER,    -- FK → persons.id
            detected_at TEXT
        );

        CREATE TABLE IF NOT EXISTS persons (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            name        TEXT,
            alias       TEXT,
            embedding_centroid BLOB,  -- 聚类中心 embedding
            face_count  INTEGER DEFAULT 0,
            created_at  TEXT,
            updated_at  TEXT
        );

        CREATE INDEX IF NOT EXISTS idx_faces_photo ON faces(photo_id);
        CREATE INDEX IF NOT EXISTS idx_faces_person ON faces(person_id);
    """)
    conn.commit()


# ── 人脸检测 ──────────────────────────────────────────────

def load_face_app():
    print("⏳ 加载人脸识别模型（首次需下载，约300MB）...")
    app = FaceAnalysis(name='buffalo_l', providers=['CPUExecutionProvider'])
    app.prepare(ctx_id=0, det_size=(640, 640))
    print("✅ 模型加载完成")
    return app


def detect_faces(db_path: str, limit=None):
    conn = sqlite3.connect(db_path)
    init_face_tables(conn)
    c = conn.cursor()

    # 只处理图片（跳过视频和已检测的）
    IMAGE_EXTS = ('.jpg', '.jpeg', '.png', '.heic', '.heif', '.bmp', '.tiff', '.tif')
    already = {r[0] for r in c.execute("SELECT DISTINCT photo_id FROM faces")}

    rows = c.execute("SELECT id, path FROM photos WHERE is_screenshot=0").fetchall()

    # 过滤已处理 + 仅图片
    rows = [(pid, path) for pid, path in rows
            if pid not in already
            and Path(path).suffix.lower() in IMAGE_EXTS]

    if limit and len(rows) > limit:
        rows = rows[:limit]

    if not rows:
        print("没有新图片需要检测。")
        return

    app = load_face_app()
    now = datetime.now().isoformat()
    total_faces = 0

    print(f"\n🔍 开始人脸检测，共 {len(rows)} 张图片...")

    for i, (photo_id, photo_path) in enumerate(rows):
        if (i+1) % 50 == 0:
            print(f"  进度: {i+1}/{len(rows)}，已发现 {total_faces} 张人脸")

        try:
            # 用 PIL 先做 EXIF 旋转，再转 cv2（确保检测坐标和显示方向一致）
            from PIL import ImageOps
            pil_img = ImageOps.exif_transpose(Image.open(photo_path).convert("RGB"))
            img = cv2.cvtColor(np.array(pil_img), cv2.COLOR_RGB2BGR)

            faces = app.get(img)
        except Exception as e:
            continue

        for face in faces:
            if face.det_score < 0.85:
                continue
            # 人脸区域最小尺寸限制
            bbox = face.bbox.tolist()
            face_w = bbox[2] - bbox[0]
            face_h = bbox[3] - bbox[1]
            if face_w < 50 or face_h < 50:
                continue

            bbox = face.bbox.tolist()

            # 人脸区域亮度过滤：跳过极暗裁剪区域（演出/夜景误检）
            x1, y1, x2, y2 = [max(0, int(v)) for v in bbox]
            h_img, w_img = img.shape[:2]
            x2 = min(w_img, x2); y2 = min(h_img, y2)
            if x2 > x1 and y2 > y1:
                face_region = cv2.cvtColor(img[y1:y2, x1:x2], cv2.COLOR_BGR2GRAY)
                if face_region.mean() < 30:  # 极暗区域，跳过
                    continue

            # 人脸区域最小尺寸过滤（太小的检测不可靠）
            face_w = bbox[2] - bbox[0]
            face_h = bbox[3] - bbox[1]
            if face_w < 50 or face_h < 50:
                continue
            embedding = face.embedding.astype(np.float32).tobytes()
            landmark = face.kps.tolist() if face.kps is not None else None

            c.execute("""
                INSERT INTO faces (photo_id, photo_path, bbox, landmark, det_score, embedding, detected_at)
                VALUES (?,?,?,?,?,?,?)
            """, (
                photo_id, photo_path,
                json.dumps(bbox),
                json.dumps(landmark) if landmark else None,
                float(face.det_score),
                embedding,
                now
            ))
            total_faces += 1

        if (i+1) % 100 == 0:
            conn.commit()

    conn.commit()
    print(f"\n✅ 检测完成: {len(rows)} 张图片，发现 {total_faces} 张人脸")


# ── 人脸聚类 ──────────────────────────────────────────────

def cluster_faces(db_path: str, eps=0.5, min_samples=2):
    """
    增量聚类：只处理 person_id IS NULL 的人脸。
    优先尝试合并到已有 person（通过 centroid 相似度），否则新建 person。
    eps: 余弦距离阈值（越小越严格，0.3-0.5 合适）
    min_samples: 同一人至少出现几次才独立成一个 person
    """
    conn = sqlite3.connect(db_path)
    init_face_tables(conn)
    c = conn.cursor()

    # 只聚类未分配的人脸
    rows = c.execute("""
        SELECT id, embedding FROM faces
        WHERE person_id IS NULL AND embedding IS NOT NULL
    """).fetchall()

    if not rows:
        print("没有未聚类的人脸。")
        conn.close()
        return

    print(f"\n🧩 对 {len(rows)} 张新人脸进行增量聚类（eps={eps}）...")

    face_ids = [r[0] for r in rows]
    embeddings = np.array([np.frombuffer(r[1], dtype=np.float32) for r in rows])
    embeddings = normalize(embeddings)

    # DBSCAN 聚类新人脸
    clustering = DBSCAN(eps=eps, min_samples=min_samples, metric='cosine').fit(embeddings)
    labels = clustering.labels_

    unique_labels = set(labels) - {-1}
    print(f"  发现 {len(unique_labels)} 个新聚类，{sum(labels==-1)} 张孤立人脸")

    now = datetime.now().isoformat()
    label_to_person = {}

    # 加载已有 persons 的 centroid，用于匹配
    existing_persons = c.execute("""
        SELECT id, embedding_centroid FROM persons
        WHERE embedding_centroid IS NOT NULL
    """).fetchall()
    existing_ids = [r[0] for r in existing_persons]
    existing_centroids = (
        normalize(np.array([np.frombuffer(r[1], dtype=np.float32) for r in existing_persons]))
        if existing_persons else np.array([])
    )

    MERGE_THRESHOLD = 0.35  # 余弦距离 < 这个值则认为是同一人

    for label in unique_labels:
        mask = labels == label
        cluster_embeddings = embeddings[mask]
        centroid = cluster_embeddings.mean(axis=0)
        centroid = centroid / np.linalg.norm(centroid)
        face_count = int(mask.sum())

        # 尝试与已有 persons 合并
        merged_person_id = None
        if len(existing_centroids) > 0:
            distances = 1 - existing_centroids.dot(centroid)  # cosine distance
            min_idx = int(np.argmin(distances))
            if distances[min_idx] < MERGE_THRESHOLD:
                merged_person_id = existing_ids[min_idx]

        if merged_person_id:
            # 合并到已有 person，更新 centroid 和 face_count
            old_centroid_bytes = c.execute(
                "SELECT embedding_centroid, face_count FROM persons WHERE id=?",
                (merged_person_id,)
            ).fetchone()
            old_count = old_centroid_bytes[1] if old_centroid_bytes else 0
            old_emb = np.frombuffer(old_centroid_bytes[0], dtype=np.float32) if old_centroid_bytes else centroid
            # 加权平均更新 centroid
            new_count = old_count + face_count
            new_centroid = (old_emb * old_count + centroid * face_count) / new_count
            new_centroid = new_centroid / np.linalg.norm(new_centroid)
            c.execute("UPDATE persons SET embedding_centroid=?, face_count=?, updated_at=? WHERE id=?",
                      (new_centroid.astype(np.float32).tobytes(), new_count, now, merged_person_id))
            label_to_person[label] = merged_person_id
        else:
            # 新建 person
            c.execute("""
                INSERT INTO persons (embedding_centroid, face_count, created_at, updated_at)
                VALUES (?,?,?,?)
            """, (centroid.astype(np.float32).tobytes(), face_count, now, now))
            label_to_person[label] = c.lastrowid

    # 分配 person_id
    for face_id, label in zip(face_ids, labels):
        if label != -1:
            c.execute("UPDATE faces SET person_id=? WHERE id=?",
                      (label_to_person[label], face_id))

    conn.commit()
    conn.close()
    new_persons = len([v for v in label_to_person.values()
                       if v not in existing_ids])
    merged_count = len(unique_labels) - new_persons
    print(f"✅ 增量聚类完成：新建 {new_persons} 个人物，合并到已有人物 {merged_count} 个")


# ── 人物命名 ──────────────────────────────────────────────

def label_persons(db_path: str, output_dir="/tmp/photomemory_faces"):
    """
    打印每个未命名人物的代表图片路径，让用户输入名字。
    """
    conn = sqlite3.connect(db_path)
    c = conn.cursor()

    os.makedirs(output_dir, exist_ok=True)

    persons = c.execute("""
        SELECT id, name, face_count FROM persons
        WHERE name IS NULL ORDER BY face_count DESC
    """).fetchall()

    if not persons:
        print("所有人物都已命名。")
        return

    print(f"\n👤 需要命名的人物: {len(persons)} 个")
    print(f"  代表图片会保存到: {output_dir}\n")

    for person_id, _, face_count in persons:
        # 取该人物检测分最高的5张代表图
        sample_faces = c.execute("""
            SELECT photo_path, bbox, det_score FROM faces
            WHERE person_id=? ORDER BY det_score DESC LIMIT 5
        """, (person_id,)).fetchall()

        print(f"── 人物 #{person_id} ({face_count}张照片) ──")

        # 裁剪人脸缩略图
        import cv2
        saved = []
        for j, (photo_path, bbox_json, score) in enumerate(sample_faces):
            try:
                img = cv2.imread(photo_path)
                if img is None:
                    continue
                bbox = json.loads(bbox_json)
                x1, y1, x2, y2 = [int(v) for v in bbox]
                # 稍微扩大一点
                pad = 20
                h, w = img.shape[:2]
                x1 = max(0, x1-pad); y1 = max(0, y1-pad)
                x2 = min(w, x2+pad); y2 = min(h, y2+pad)
                face_crop = img[y1:y2, x1:x2]
                out_path = os.path.join(output_dir, f"person_{person_id}_sample{j+1}.jpg")
                cv2.imwrite(out_path, face_crop)
                saved.append(out_path)
            except Exception:
                pass

        for p in saved:
            print(f"  📷 {p}")

        name = input(f"  输入姓名 (回车跳过): ").strip()
        if name:
            c.execute("UPDATE persons SET name=?, updated_at=? WHERE id=?",
                      (name, datetime.now().isoformat(), person_id))
            conn.commit()
            print(f"  ✅ 已命名: {name}")

    print("\n命名完成。")


# ── 统计 ──────────────────────────────────────────────────

def print_stats(db_path: str):
    conn = sqlite3.connect(db_path)
    c = conn.cursor()

    total_faces = c.execute("SELECT COUNT(*) FROM faces").fetchone()[0]
    named = c.execute("SELECT COUNT(*) FROM persons WHERE name IS NOT NULL").fetchone()[0]
    unnamed = c.execute("SELECT COUNT(*) FROM persons WHERE name IS NULL").fetchone()[0]

    print(f"\n📊 人脸统计:")
    print(f"   总人脸数    : {total_faces:,}")
    print(f"   已命名人物  : {named}")
    print(f"   未命名人物  : {unnamed}")

    if named > 0:
        print("\n  已命名人物:")
        for row in c.execute("""
            SELECT p.name, p.face_count,
                   COUNT(DISTINCT f.photo_path) as photo_count
            FROM persons p
            JOIN faces f ON f.person_id = p.id
            WHERE p.name IS NOT NULL
            GROUP BY p.id ORDER BY p.face_count DESC
        """):
            print(f"    {row[0]}: {row[2]} 张照片")


# ── 主入口 ────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="PhotoMemory Phase 2 - 人脸识别")
    parser.add_argument("--db", default="./photomemory.db")
    parser.add_argument("--detect", action="store_true", help="检测所有图片人脸")
    parser.add_argument("--cluster", action="store_true", help="聚类人脸 → 人物")
    parser.add_argument("--label", action="store_true", help="交互式命名人物")
    parser.add_argument("--stats", action="store_true", help="显示统计")
    parser.add_argument("--eps", type=float, default=0.6, help="聚类阈值(0.5-0.7，越大越宽松)")
    parser.add_argument("--limit", type=int, help="限制检测张数（测试用）")
    args = parser.parse_args()

    if args.detect:
        detect_faces(args.db, limit=args.limit)
    elif args.cluster:
        cluster_faces(args.db, eps=args.eps)
    elif args.label:
        label_persons(args.db)
    elif args.stats:
        print_stats(args.db)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
