from __future__ import annotations

import argparse
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(prog="flowtwin", description="FlowTwin AI - offline process monitoring demo")
    sub = parser.add_subparsers(dest="command", required=True)

    download = sub.add_parser("download", help="download and verify the source XES file")
    download.add_argument("--force", action="store_true", help="download the file again")

    prepare = sub.add_parser("prepare", help="stream the XES log into a local SQLite database")
    prepare.add_argument("--xes", type=Path, help="optional path to a local .xes or .xes.gz file")

    sub.add_parser("train", help="train the model and write held-out test metrics")

    serve = sub.add_parser("serve", help="start the local dashboard and API")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", default=8000, type=int)

    args = parser.parse_args()
    if args.command == "download":
        from .download import download_dataset

        download_dataset(force=args.force)
    elif args.command == "prepare":
        from .prepare import prepare_data

        prepare_data(args.xes)
    elif args.command == "train":
        from .train import train_model

        train_model()
    elif args.command == "serve":
        import uvicorn

        # API requests may carry case identifiers in their query strings.
        # Avoid writing those identifiers to the default access log.
        uvicorn.run("flowtwin.web:app", host=args.host, port=args.port, reload=False, access_log=False)


if __name__ == "__main__":
    main()
