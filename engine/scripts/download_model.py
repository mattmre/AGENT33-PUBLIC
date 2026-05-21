#!/usr/bin/env python3
"""Download and prepare models for AirLLM layer-sharded inference."""

from __future__ import annotations

import argparse
import sys

POPULAR_MODELS = {
    "llama3-70b": "meta-llama/Meta-Llama-3-70B-Instruct",
    "qwen72b": "Qwen/Qwen2-72B-Instruct",
    "mistral-large": "mistralai/Mistral-Large-Instruct-2407",
    "llama3-8b": "meta-llama/Meta-Llama-3-8B-Instruct",
}


def download(model_id: str, output_dir: str) -> None:
    """Download a model from HuggingFace Hub."""
    try:
        from huggingface_hub import snapshot_download
    except ImportError:
        print("Install huggingface_hub: pip install huggingface_hub")
        sys.exit(1)

    print(f"Downloading {model_id} to {output_dir}...")
    snapshot_download(
        repo_id=model_id,
        local_dir=output_dir,
        local_dir_use_symlinks=False,
    )
    print(f"Done. Model saved to {output_dir}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Download models for AirLLM")
    parser.add_argument(
        "model",
        help=f"Model ID or alias. Aliases: {', '.join(POPULAR_MODELS)}",
    )
    parser.add_argument(
        "--output", "-o",
        default="/models",
        help="Output directory (default: /models)",
    )
    args = parser.parse_args()

    model_id = POPULAR_MODELS.get(args.model, args.model)
    output = f"{args.output}/{model_id}"
    download(model_id, output)


if __name__ == "__main__":
    main()
