#!/usr/bin/env python3
"""Export one immutable V2 Runtime Bundle from Codify's database."""
from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

from app.core.worker_runtime_bundle_export import (
    RuntimeBundleExportError,
    export_runtime_bundle,
    load_exportable_runtime_bundle,
)
from app.database import AsyncSessionLocal, close_db


async def _main(args: argparse.Namespace) -> int:
    try:
        async with AsyncSessionLocal() as db:
            bundle = await load_exportable_runtime_bundle(
                db, task_id=args.task_id, bundle_digest=args.bundle_digest
            )
        metadata = export_runtime_bundle(bundle, args.output_dir)
    except RuntimeBundleExportError as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, sort_keys=True))
        return 2
    finally:
        await close_db()
    print(json.dumps({"ok": True, **metadata}, sort_keys=True))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    selector = parser.add_mutually_exclusive_group(required=True)
    selector.add_argument("--task-id", type=int)
    selector.add_argument("--bundle-digest")
    parser.add_argument("--output-dir", type=Path, required=True)
    return asyncio.run(_main(parser.parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
