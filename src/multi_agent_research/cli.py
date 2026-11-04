import argparse
import asyncio
import json
import logging
from pathlib import Path

import httpx

from .config import RunConfig
from .frames import DEFAULT_CORPUS


def main():
    parser = argparse.ArgumentParser(description="Question-scoped, offline-evidence FRAMES QA baseline")
    parser.add_argument("--corpus-dir", type=Path, default=DEFAULT_CORPUS)
    parser.add_argument("--sample-size", type=int, default=10)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--question-ids", nargs="+", help="Explicit TSV row IDs, overriding sampling")
    parser.add_argument("--config", type=Path)
    parser.add_argument("--output-dir", type=Path)
    strategy = parser.add_mutually_exclusive_group()
    strategy.add_argument("--full-restart", action="store_true",
                          help="Restart once after an explicit injection, with the saved baseline and fresh state")
    strategy.add_argument("--always-verify", action="store_true",
                          help="Diagnose actual boundary inputs/outputs without rewriting results")
    args = parser.parse_args()
    logging.basicConfig(format="%(message)s")
    logging.getLogger("multi_agent_research").setLevel(logging.INFO)
    try:
        from .benchmark import run_frames
        from .models.adapter import OpenAIChatCompletionsAdapter

        config = RunConfig.load(args.config) if args.config else RunConfig()
        if args.output_dir:
            config.output_dir = args.output_dir
        if args.full_restart or args.always_verify:
            config = RunConfig.model_validate({
                **config.model_dump(),
                "full_restart": args.full_restart, "always_verify": args.always_verify,
            })
        result = asyncio.run(run_frames(
            config, OpenAIChatCompletionsAdapter(), corpus_dir=args.corpus_dir,
            size=args.sample_size, seed=args.seed, question_ids=args.question_ids,
        ))
        success = all(r["status"] == "completed" and r.get("grade", {}).get("correct") is not None
                      for r in result["results"])
    except KeyError as exc:
        parser.exit(1, f"Required setting is unavailable: {exc}\n")
    except (OSError, ValueError, httpx.HTTPError) as exc:
        parser.exit(1, f"QA run failed: {exc}\n")
    print(json.dumps(result, indent=2))
    raise SystemExit(0 if success else 1)


if __name__ == "__main__":
    main()
