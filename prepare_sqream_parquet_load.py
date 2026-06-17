#!/usr/bin/env python3

from __future__ import annotations

import argparse
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent
STAGING_DIR = BASE_DIR / "staging"
TEMPLATE_PATH = BASE_DIR / "sqream_parquet_load_template.sql"


def render_sql(template: str, features_path: str, events_path: str) -> str:
    return (
        template.replace("{{FEATURES_PARQUET_PATH}}", features_path.replace("'", "''"))
        .replace("{{EVENTS_PARQUET_PATH}}", events_path.replace("'", "''"))
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--shared-path", required=True, help="Directory visible to the worker selected by SQream server_picker")
    parser.add_argument("--batch-no", type=int, default=1)
    parser.add_argument("--output-sql", default=str(BASE_DIR / "generated_sqream_parquet_load.sql"))
    args = parser.parse_args()

    feature_file = STAGING_DIR / f"symbol_features_batch_{args.batch_no}.parquet"
    event_file = STAGING_DIR / f"symbol_events_batch_{args.batch_no}.parquet"
    if not feature_file.exists():
        raise SystemExit(f"missing staging file: {feature_file}")
    if not event_file.exists():
        raise SystemExit(f"missing staging file: {event_file}")

    shared = args.shared_path.rstrip("/")
    feature_path = f"{shared}/{feature_file.name}"
    event_path = f"{shared}/{event_file.name}"
    template = TEMPLATE_PATH.read_text(encoding="utf-8")
    sql = render_sql(template, feature_path, event_path)

    output_sql = Path(args.output_sql)
    output_sql.write_text(sql, encoding="utf-8")

    print(f"feature_parquet={feature_file}")
    print(f"event_parquet={event_file}")
    print(f"sqream_feature_path={feature_path}")
    print(f"sqream_event_path={event_path}")
    print(f"output_sql={output_sql}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
