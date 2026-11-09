from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .metrics import summarize
from .policy import allowlist_policy
from .runner import load_cases, run_ollama, run_policy, save_results


def main() -> int:
    parser = argparse.ArgumentParser(description="Benchmark AI-agent permission decisions on synthetic cases.")
    parser.add_argument("--policy", choices=["allowlist", "ollama"], default="allowlist")
    parser.add_argument("--model", help="Local Ollama model tag, e.g. qwen2.5:7b")
    parser.add_argument("--data", type=Path, default=None, help="Optional scenario JSON file")
    parser.add_argument("--out", type=Path, default=None, help="Optional JSON report destination")
    args = parser.parse_args()
    try:
        cases = load_cases(args.data) if args.data else load_cases()
        rows = run_policy(cases, allowlist_policy) if args.policy == "allowlist" else run_ollama(cases, args.model)
        report = summarize(rows)
    except (OSError, ValueError, RuntimeError, json.JSONDecodeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    payload = {"policy": args.policy, "model": args.model if args.policy == "ollama" else None, "metrics": report}
    print(json.dumps(payload, indent=2))
    if args.out:
        save_results(args.out, args.policy, rows, report)
        print(f"saved report: {args.out}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
