import argparse
import asyncio
import json
from pathlib import Path

from .config import RunConfig
from .runner import run_research


def main():
    parser = argparse.ArgumentParser(description="Instrumented multi-agent research baseline")
    parser.add_argument("query", nargs="?", default="Research alpha, beta, and gamma.")
    parser.add_argument("--config", type=Path)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--demo", action="store_true", help="Offline scripted two-round run")
    args = parser.parse_args()
    config = RunConfig.load(args.config) if args.config else RunConfig()
    if args.output_dir:
        config.output_dir = args.output_dir
    if args.demo:
        from .demo import DemoFetcher, DemoModel, DemoSearch

        model, search, fetcher = DemoModel(), DemoSearch(), DemoFetcher()
    else:
        from .models.adapter import OpenAIChatCompletionsAdapter
        from .tools.fetch import PageFetcher
        from .tools.search import TavilySearch

        model, search, fetcher = OpenAIChatCompletionsAdapter(), TavilySearch(), PageFetcher()
    result = asyncio.run(run_research(args.query, config, model, search, fetcher))
    print(json.dumps(result, indent=2))
    raise SystemExit(0 if result["status"] == "completed" else 1)


if __name__ == "__main__":
    main()
