"""Console entrypoint for the independent Dataset Manager HTTP process."""

import argparse

import uvicorn

from pbl4.dataset_manager.app import create_app
from pbl4.dataset_manager.config import DatasetManagerConfig


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="pbl4-dataset-manager",
        description="PBL4 Dataset Ingestion, Partitioning, and Serving Service.",
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=9200)
    parser.add_argument("--store-dir", default="var/datasets")
    parser.add_argument("--temp-dir", default="var/datasets-tmp")
    parser.add_argument("--queue-capacity", type=int, default=8)
    parser.add_argument("--public-base-url")
    args = parser.parse_args()
    config = DatasetManagerConfig(
        host=args.host,
        port=args.port,
        store_dir=args.store_dir,
        temp_dir=args.temp_dir,
        queue_capacity=args.queue_capacity,
        public_base_url=args.public_base_url or f"http://{args.host}:{args.port}",
    )
    uvicorn.run(
        create_app(config), host=config.host, port=config.port, log_level=config.log_level.lower()
    )


if __name__ == "__main__":
    main()
