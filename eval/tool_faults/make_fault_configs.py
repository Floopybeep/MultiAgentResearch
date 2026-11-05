"""Emit one fault config per experiment condition.

A condition is a (question, denied document, fault mode, scenario) cell. Each
emitted YAML is the base fault config with `tool_failure` armed against that one
document and the scenario baked in as `full_restart` / `always_verify`, so no
CLI strategy flag is needed and the effective settings recorded in the run's
`batch.json` fully describe the condition.

Targets are document-level and persistent: `offsets: []` denies every page and
`max_failures: null` never lifts the denial, which is the strongest accidental
denial available at this boundary. Per-page transient denial gets routed around.

    # 28-pair dependency sweep (§5)
    python eval/tool_faults/make_fault_configs.py --out runs/configs/sweep \
        --questions eval/shared_10_question_ids.txt \
        --modes immediate --scenarios baseline

    # three-scenario cross over chosen targets (§6)
    python eval/tool_faults/make_fault_configs.py --out runs/configs/tier2 \
        --pairs eval/tool_faults/targets_section6.tsv \
        --modes immediate timeout --scenarios baseline full-restart always-verify
"""

import argparse
import json
from pathlib import Path

import yaml

from multi_agent_research.config import RunConfig

SCENARIOS = {
    "baseline": {"full_restart": False, "always_verify": False},
    "full-restart": {"full_restart": True, "always_verify": False},
    "always-verify": {"full_restart": False, "always_verify": True},
}


def catalog_pairs(question_ids, corpus_dir: Path):
    """Every (question, document) pair in those questions' catalogs."""
    index = json.loads((corpus_dir / "index.json").read_text())["questions"]
    return [(qid, doc) for qid in question_ids for doc in index[qid]]


def read_pairs(path: Path):
    """`question_id<whitespace>document_id` per line; `#` comments ignored."""
    pairs = []
    for line in path.read_text().splitlines():
        line = line.split("#", 1)[0].strip()
        if line:
            qid, doc = line.split()
            pairs.append((qid, doc))
    return pairs


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--base", type=Path, default=Path("configs/faults-tool-read-denial.yaml"))
    parser.add_argument("--out", type=Path, required=True, help="Scratch dir for generated YAML")
    parser.add_argument("--corpus-dir", type=Path, default=Path("corpus"))
    parser.add_argument("--questions", type=Path, help="Whitespace-separated question IDs; sweeps each full catalog")
    parser.add_argument("--pairs", type=Path, help="Explicit `question_id document_id` lines")
    parser.add_argument("--modes", nargs="+", default=["immediate"], choices=["immediate", "timeout"])
    parser.add_argument("--scenarios", nargs="+", default=["baseline"], choices=sorted(SCENARIOS))
    parser.add_argument("--cells", nargs="+", metavar="MODE:SCENARIO",
                        help="Explicit mode:scenario cells, overriding the --modes x "
                             "--scenarios cross. Tier 2 is not a clean cross product -- it "
                             "is immediate:full-restart, immediate:always-verify and "
                             "timeout:full-restart -- so expressing it needs this rather "
                             "than two invocations into two directories.")
    parser.add_argument("--manifest", default="manifest.json",
                        help="Manifest filename inside --out")
    args = parser.parse_args()

    if args.cells:
        cells = []
        for spec in args.cells:
            mode, _, scenario = spec.partition(":")
            if mode not in ("immediate", "timeout") or scenario not in SCENARIOS:
                parser.error(f"bad --cells entry {spec!r}; expected MODE:SCENARIO")
            cells.append((mode, scenario))
    else:
        cells = [(m, s) for m in args.modes for s in args.scenarios]

    if args.pairs:
        pairs = read_pairs(args.pairs)
    elif args.questions:
        pairs = catalog_pairs(args.questions.read_text().split(), args.corpus_dir)
    else:
        parser.error("one of --questions or --pairs is required")

    base = yaml.safe_load(args.base.read_text())
    args.out.mkdir(parents=True, exist_ok=True)
    manifest = []
    for question_id, document_id in pairs:
        for mode, scenario in cells:
            name = f"q{question_id}_{document_id}_{mode}_{scenario}"
            strategy = SCENARIOS[scenario]
            # config.py separate_strategies raises on both; fail here, not mid-sweep.
            assert not (strategy["full_restart"] and strategy["always_verify"]), scenario
            config = {
                **base,
                **strategy,
                "tool_failure": {
                    **base["tool_failure"],
                    "enabled": True,
                    "mode": mode,
                    "document_ids": [document_id],
                    "offsets": [],
                    "persistent": True,
                    "max_failures": None,
                },
            }
            path = args.out / f"{name}.yaml"
            path.write_text(yaml.safe_dump(config, sort_keys=False))
            RunConfig.load(path)  # fail here, not forty minutes into a sweep
            manifest.append({
                "name": name, "question_id": question_id, "document_id": document_id,
                "mode": mode, "scenario": scenario, "config": str(path),
            })

    manifest_path = args.out / args.manifest
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")
    print(f"{len(manifest)} conditions -> {args.out}\nmanifest: {manifest_path}")


if __name__ == "__main__":
    main()
