"""对已启动的 CCD 展示服务执行只读混合负载，并输出可复现的 JSON 报告。"""
from __future__ import annotations

import argparse
import concurrent.futures
from datetime import datetime, timezone
import json
from pathlib import Path
import random
import statistics
import time

import httpx


ENDPOINTS = (
    ("products", "/api/public/products?limit=80", 35),
    ("tags", "/api/public/products?limit=80&tags=%E6%96%B0%E6%89%8B%E6%8E%A8%E8%8D%90", 20),
    ("query", "/api/public/products?limit=80&query=%E4%BD%B3%E8%83%BD", 20),
    ("sections", "/api/public/sections", 15),
    ("filters", "/api/public/filters", 10),
)


def percentile(values: list[float], ratio: float) -> float:
    if not values:
        return 0.0
    return sorted(values)[max(0, min(len(values) - 1, int(len(values) * ratio) - 1))]


def summarize(values: list[float]) -> dict[str, float | int]:
    return {
        "count": len(values),
        "p50_ms": round(statistics.median(values), 2) if values else 0.0,
        "p95_ms": round(percentile(values, 0.95), 2),
        "max_ms": round(max(values), 2) if values else 0.0,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="CCD 展示服务只读性能基准")
    parser.add_argument("--base-url", default="http://127.0.0.1:8899")
    parser.add_argument("--database", default="", help="仅记录受测数据库或副本路径")
    parser.add_argument("--connection-mode", default="shared-rlock", help="仅记录连接策略")
    parser.add_argument("--concurrency", type=int, default=20)
    parser.add_argument("--duration", type=int, default=300)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.concurrency < 1 or args.duration < 1:
        parser.error("并发数和持续时间必须大于零")

    names = [item[0] for item in ENDPOINTS]
    paths = {item[0]: item[1] for item in ENDPOINTS}
    weights = [item[2] for item in ENDPOINTS]
    deadline = time.monotonic() + args.duration

    def worker(seed: int):
        rng = random.Random(seed)
        timings: list[tuple[str, float]] = []
        errors: list[dict[str, object]] = []
        with httpx.Client(base_url=args.base_url, timeout=30) as client:
            while time.monotonic() < deadline:
                name = rng.choices(names, weights=weights, k=1)[0]
                started = time.perf_counter()
                try:
                    response = client.get(paths[name])
                    elapsed = (time.perf_counter() - started) * 1000
                    timings.append((name, elapsed))
                    if response.status_code != 200:
                        errors.append({"endpoint": name, "status": response.status_code})
                except Exception as error:  # 基准报告需要保留超时等失败，而不是中止整轮。
                    errors.append({"endpoint": name, "error": type(error).__name__})
        return timings, errors

    started_at = datetime.now(timezone.utc).isoformat()
    started = time.perf_counter()
    all_timings: list[tuple[str, float]] = []
    errors: list[dict[str, object]] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.concurrency) as executor:
        for timings, worker_errors in executor.map(worker, range(args.concurrency)):
            all_timings.extend(timings)
            errors.extend(worker_errors)
    elapsed = time.perf_counter() - started
    report = {
        "started_at": started_at,
        "base_url": args.base_url,
        "database": args.database,
        "connection_mode": args.connection_mode,
        "concurrency": args.concurrency,
        "requested_duration_seconds": args.duration,
        "actual_duration_seconds": round(elapsed, 2),
        "requests_per_second": round(len(all_timings) / elapsed, 2),
        "overall": summarize([value for _, value in all_timings]),
        "endpoints": {
            name: summarize([value for endpoint, value in all_timings if endpoint == name])
            for name in names
        },
        "errors": errors[:100],
        "error_count": len(errors),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
