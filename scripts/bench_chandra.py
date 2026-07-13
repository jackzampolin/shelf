#!/usr/bin/env python3
"""Concurrency sweep benchmark for the chandra OCR vLLM backends.

Finds the throughput knee for shelf's chandra max_concurrency setting by
replaying real page images through the same OpenAI-compatible chat request
shape internal/providers/chandra_ocr.go sends, at increasing concurrency
levels, split evenly across endpoints.

Run ONLY when the pipeline is idle (chandra shares the spark GPU with qwen;
a live run contaminates both the measurement and the run).

Usage:
  python3 scripts/bench_chandra.py \
    --endpoints http://100.74.68.88:8001/v1,http://100.86.62.91:8001/v1 \
    --pages-dir ~/.shelf/source_images \
    --levels 8,16,24,32,48,64 \
    --requests-per-level 48

Output: per-level table (throughput pages/min, latency p50/p95, errors,
KV-cache peak, preemptions delta per endpoint) plus a JSON blob for records.
Stdlib only; uses threads (requests are I/O bound).
"""

import argparse
import base64
import concurrent.futures
import glob
import json
import os
import random
import statistics
import sys
import threading
import time
import urllib.request

# Mirrors DefaultChandraOCRPrompt in internal/providers/chandra_ocr.go closely
# enough for representative prefill length; exact parity is not required for
# throughput measurement, but we load the real one from the Go source when run
# from the repo root so drift never invalidates results.
FALLBACK_PROMPT = "OCR this image to HTML, arranged as layout blocks."


def load_real_prompt():
    src = os.path.join(os.path.dirname(__file__), "..", "internal", "providers", "chandra_ocr.go")
    try:
        text = open(src).read()
        start = text.index("DefaultChandraOCRPrompt = `") + len("DefaultChandraOCRPrompt = `")
        end = text.index("`", start)
        return text[start:end]
    except Exception:
        return FALLBACK_PROMPT


def pick_pages(pages_dir, count):
    pages = glob.glob(os.path.join(os.path.expanduser(pages_dir), "*", "page_*.png"))
    if len(pages) < count:
        raise SystemExit(f"only {len(pages)} pages under {pages_dir}, need {count}")
    random.seed(42)  # same sample every run -> comparable sweeps
    return random.sample(pages, count)


def vllm_gauge(endpoint, names):
    """Scrape named gauges/counters from a vLLM /metrics endpoint."""
    base = endpoint.rsplit("/v1", 1)[0]
    out = {}
    try:
        with urllib.request.urlopen(f"{base}/metrics", timeout=5) as r:
            for line in r.read().decode().splitlines():
                for n in names:
                    if line.startswith(f"vllm:{n}{{"):
                        out[n] = float(line.rsplit(" ", 1)[1])
    except Exception:
        pass
    return out


def ocr_request(endpoint, prompt, image_b64, max_tokens, timeout):
    payload = json.dumps({
        "model": "datalab-to/chandra-ocr-2",
        "messages": [{
            "role": "user",
            "content": [
                {"type": "text", "text": prompt},
                {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{image_b64}"}},
            ],
        }],
        "temperature": 0.0,
        "top_p": 0.1,
        "max_tokens": max_tokens,
    }).encode()
    req = urllib.request.Request(
        f"{endpoint}/chat/completions", data=payload,
        headers={"Content-Type": "application/json"})
    start = time.monotonic()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            body = json.load(r)
        elapsed = time.monotonic() - start
        usage = body.get("usage") or {}
        return {"ok": True, "seconds": elapsed,
                "completion_tokens": usage.get("completion_tokens", 0)}
    except Exception as e:
        return {"ok": False, "seconds": time.monotonic() - start, "error": str(e)[:120]}


def run_level(level, images, endpoints, prompt, max_tokens, timeout):
    counters = {"i": 0}
    lock = threading.Lock()

    def next_endpoint():
        with lock:
            ep = endpoints[counters["i"] % len(endpoints)]
            counters["i"] += 1
            return ep

    pre = {ep: vllm_gauge(ep, ["num_preemptions_total", "kv_cache_usage_perc"]) for ep in endpoints}
    start = time.monotonic()
    results = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=level) as pool:
        futs = [pool.submit(ocr_request, next_endpoint(), prompt, img, max_tokens, timeout)
                for img in images]
        for f in concurrent.futures.as_completed(futs):
            results.append(f.result())
    wall = time.monotonic() - start
    post = {ep: vllm_gauge(ep, ["num_preemptions_total", "kv_cache_usage_perc"]) for ep in endpoints}

    ok = [r for r in results if r["ok"]]
    lat = sorted(r["seconds"] for r in ok)
    return {
        "concurrency": level,
        "requests": len(results),
        "ok": len(ok),
        "errors": len(results) - len(ok),
        "error_samples": [r["error"] for r in results if not r["ok"]][:3],
        "wall_seconds": round(wall, 1),
        "pages_per_min": round(len(ok) / wall * 60, 1) if wall else 0,
        "latency_p50": round(statistics.median(lat), 1) if lat else None,
        "latency_p95": round(lat[max(0, int(len(lat) * 0.95) - 1)], 1) if lat else None,
        "completion_tok_per_s": round(sum(r["completion_tokens"] for r in ok) / wall, 0) if wall else 0,
        "preemptions_delta": {
            ep: (post.get(ep, {}).get("num_preemptions_total", 0) or 0)
              - (pre.get(ep, {}).get("num_preemptions_total", 0) or 0)
            for ep in endpoints},
        "kv_cache_peak_hint": {ep: post.get(ep, {}).get("kv_cache_usage_perc") for ep in endpoints},
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--endpoints", required=True, help="comma-separated /v1 base URLs")
    ap.add_argument("--pages-dir", default="~/.shelf/source_images")
    ap.add_argument("--levels", default="8,16,24,32,48,64")
    ap.add_argument("--requests-per-level", type=int, default=48)
    ap.add_argument("--max-tokens", type=int, default=12384)
    ap.add_argument("--timeout", type=int, default=300)
    ap.add_argument("--out", default="")
    args = ap.parse_args()

    endpoints = [e.strip().rstrip("/") for e in args.endpoints.split(",")]
    levels = [int(x) for x in args.levels.split(",")]
    prompt = load_real_prompt()

    pages = pick_pages(args.pages_dir, args.requests_per_level)
    print(f"loading {len(pages)} page images...", file=sys.stderr)
    images = [base64.b64encode(open(p, "rb").read()).decode() for p in pages]

    # Warm-up: one request per endpoint so model/graph warm state doesn't skew level 1.
    for ep in endpoints:
        ocr_request(ep, prompt, images[0], args.max_tokens, args.timeout)

    rows = []
    for level in levels:
        print(f"level {level}: {len(images)} requests across {len(endpoints)} endpoints...",
              file=sys.stderr)
        row = run_level(level, images, endpoints, prompt, args.max_tokens, args.timeout)
        rows.append(row)
        print(f"  -> {row['pages_per_min']} pages/min, p50 {row['latency_p50']}s, "
              f"p95 {row['latency_p95']}s, errors {row['errors']}, "
              f"preemptions {row['preemptions_delta']}", file=sys.stderr)

    print(f"\n{'conc':>5} {'pages/min':>10} {'p50 s':>7} {'p95 s':>7} {'errs':>5} {'tok/s':>7}")
    for r in rows:
        print(f"{r['concurrency']:>5} {r['pages_per_min']:>10} {r['latency_p50']:>7} "
              f"{r['latency_p95']:>7} {r['errors']:>5} {r['completion_tok_per_s']:>7}")

    best = max(rows, key=lambda r: (r["errors"] == 0, r["pages_per_min"]))
    print(f"\nknee candidate: concurrency {best['concurrency']} "
          f"at {best['pages_per_min']} pages/min (verify latency is acceptable)")

    if args.out:
        with open(os.path.expanduser(args.out), "w") as f:
            json.dump(rows, f, indent=2)
        print(f"wrote {args.out}")


if __name__ == "__main__":
    main()
