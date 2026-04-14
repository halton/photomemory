#!/usr/bin/env python3
import argparse
import time
import requests
from prettytable import PrettyTable

ROUTES = [
    ("统计", "/api/stats"),
    ("照片列表", "/api/photos/random"),
    ("人物列表", "/api/persons"),
    ("搜索", "/api/search"),
]

def request_route(host, port, route, token=None):
    url = f"http://{host}:{port}{route}"
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    start = time.time()
    try:
        r = requests.get(url, headers=headers, timeout=30)
        cost = (time.time() - start) * 1000
        ok = r.status_code == 200
    except Exception:
        cost = None
        ok = False
    return cost, ok

def benchmark(host, port, token, rounds):
    results = {name: [] for name, _ in ROUTES}
    for _ in range(rounds):
        for name, route in ROUTES:
            cost, ok = request_route(host, port, route, token)
            if ok and cost is not None:
                results[name].append(cost)
            else:
                results[name].append(None)
    t = PrettyTable(["端点名", "平均(ms)", "最小(ms)", "最大(ms)"])
    for name in results:
        times = [t for t in results[name] if t is not None]
        if times:
            avg = round(sum(times)/len(times), 1)
            mi = round(min(times), 1)
            ma = round(max(times), 1)
            t.add_row([name, avg, mi, ma])
        else:
            t.add_row([name, "失败", "失败", "失败"])
    print(t)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="API Benchmark Script")
    parser.add_argument("--host", type=str, default="localhost", help="主机名 (默认: localhost)")
    parser.add_argument("--port", type=int, default=5001, help="端口 (默认: 5001)")
    parser.add_argument("--token", type=str, default=None, help="认证 Token")
    parser.add_argument("--rounds", type=int, default=3, help="每个端点请求次数 (默认: 3)")
    args = parser.parse_args()
    benchmark(args.host, args.port, args.token, args.rounds)
