import sqlite3
import numpy as np
from collections import defaultdict

try:
    from sklearn.cluster import DBSCAN
except ImportError:
    import subprocess
    subprocess.check_call(["/usr/bin/python3", "-m", "pip", "install", "scikit-learn"])
    from sklearn.cluster import DBSCAN

DB_PATH = '/tmp/photomemory.db'

conn = sqlite3.connect(DB_PATH)
c = conn.cursor()

# 1. 读取所有 faces 的 embedding
c.execute("SELECT id, embedding FROM faces WHERE embedding IS NOT NULL")
rows = c.fetchall()
face_ids = []
embeddings = []
for face_id, emb in rows:
    face_ids.append(face_id)
    embeddings.append(np.frombuffer(emb, dtype=np.float32))
embeddings = np.stack(embeddings, axis=0)

# 2. DBSCAN 聚类
clusterer = DBSCAN(eps=0.5, min_samples=2, metric='cosine')
labels = clusterer.fit_predict(embeddings)

# 3. 为每个 cluster 创建人物
clusters = defaultdict(list)
for i, label in enumerate(labels):
    if label != -1:
        clusters[label].append(i)

person_rows = []  # (face_count, centroid, label) for INSERT
for label, idxs in clusters.items():
    faces_in_cluster = embeddings[idxs]
    centroid = np.mean(faces_in_cluster, axis=0).astype(np.float32)
    person_rows.append((len(idxs), centroid, label))

# 写入 persons 并获取 id
person_id_map = {}  # label: person_id
for face_count, centroid, label in person_rows:
    c.execute("INSERT INTO persons (name, face_count, embedding_centroid) VALUES (?, ?, ?)",
              (None, face_count, centroid.tobytes()))
    person_id = c.lastrowid
    person_id_map[label] = person_id
conn.commit()

# 更新 faces.person_id
for i, label in enumerate(labels):
    if label != -1:
        pid = person_id_map[label]
        c.execute("UPDATE faces SET person_id = ? WHERE id = ?", (pid, face_ids[i]))
conn.commit()

# 输出统计
person_count = len(person_id_map)
face_count = len(face_ids)
noise_count = (labels == -1).sum()
print(f"检测到 {person_count} 个人物，共 {face_count} 张人脸，{noise_count} 张噪声")

conn.close()
