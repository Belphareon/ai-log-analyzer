import argparse
import importlib
import json
import runpy
import sys
from pathlib import Path


def _extract_errors(payload):
    if isinstance(payload, list):
        return payload

    if isinstance(payload, dict):
        for key in ("errors", "logs", "items", "events", "data"):
            value = payload.get(key)
            if isinstance(value, list):
                return value

        hits = payload.get("hits")
        if isinstance(hits, dict) and isinstance(hits.get("hits"), list):
            out = []
            for item in hits["hits"]:
                if isinstance(item, dict):
                    out.append(item.get("_source", item))
            return out
        if isinstance(hits, list):
            out = []
            for item in hits:
                if isinstance(item, dict):
                    out.append(item.get("_source", item))
            return out

    raise ValueError(
        "Unsupported data format in input file. Expected raw logs as list, or dict with errors/logs/data/hits. "
        "Backfill summary files (with keys like summary/results) are not usable as source logs."
    )


def main():
    parser = argparse.ArgumentParser(
        description="Run _peak_full_investigation.py with optional cached input file."
    )
    parser.add_argument(
        "--use-data-file",
        dest="use_data_file",
        default=None,
        help="Path to JSON file with previously fetched source logs.",
    )
    parser.add_argument(
        "--save-data-file",
        dest="save_data_file",
        default=None,
        help="Path to save fetched source logs JSON for next runs.",
    )
    parser.add_argument(
        "--script",
        dest="target_script",
        default="scripts/_peak_full_investigation.py",
        help="Target investigation script path.",
    )
    args = parser.parse_args()

    repo = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(repo / "scripts"))
    sys.path.insert(0, str(repo))

    fetch_module = importlib.import_module("scripts.core.fetch_unlimited")

    original_fetch = fetch_module.fetch_unlimited

    if args.use_data_file:
        data_path = (repo / args.use_data_file).resolve() if not Path(args.use_data_file).is_absolute() else Path(args.use_data_file)
        payload = json.loads(data_path.read_text(encoding="utf-8"))
        cached_errors = _extract_errors(payload)

        def _fetch_from_file(_start_time, _end_time):
            print(f"[cache] using source data file: {data_path} (records={len(cached_errors)})")
            return cached_errors

        fetch_module.fetch_unlimited = _fetch_from_file

    elif args.save_data_file:
        save_path = (repo / args.save_data_file).resolve() if not Path(args.save_data_file).is_absolute() else Path(args.save_data_file)

        def _fetch_and_save(start_time, end_time):
            rows = original_fetch(start_time, end_time)
            save_path.parent.mkdir(parents=True, exist_ok=True)
            save_path.write_text(json.dumps(rows, ensure_ascii=False), encoding="utf-8")
            print(f"[cache] saved source data file: {save_path} (records={len(rows)})")
            return rows

        fetch_module.fetch_unlimited = _fetch_and_save

    target_script = (repo / args.target_script).resolve() if not Path(args.target_script).is_absolute() else Path(args.target_script)
    runpy.run_path(str(target_script), run_name="__main__")


if __name__ == "__main__":
    main()
