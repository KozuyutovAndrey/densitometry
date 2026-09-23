"""Optional subprocess boundary around the upstream DXA-to-3D inference."""
import argparse
import json
import os
import sys
from pathlib import Path


def validate_points(points):
    import math
    if not isinstance(points, list) or not 2 <= len(points) <= 10000:
        raise ValueError("Expected Nx3 points")
    if any(not isinstance(p, list) or len(p) != 3 or any(not isinstance(v, (int, float)) or not math.isfinite(v) for v in p) for p in points):
        raise ValueError("Invalid 3D coordinates")
    return points


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    repo = Path(os.environ["DXA3D_REPO"]).resolve()
    checkpoint = Path(os.environ["DXA3D_CHECKPOINT"]).resolve()
    if not (repo / "inference.py").is_file() or not checkpoint.is_file():
        raise FileNotFoundError("DXA-to-3D source/checkpoint missing")
    sys.path.insert(0, str(repo))
    from config import InferenceConfig
    from inference import SpineEstimator
    config = InferenceConfig(model_checkpoint=str(checkpoint), output_dir=str(Path(args.output).parent))
    estimator = SpineEstimator(config)
    result = estimator.predict_single(args.input, visualize=False, save_results=False)
    points = validate_points(result["spine_3d"].tolist())
    Path(args.output).write_text(json.dumps({"points": points, "units": "model_coordinates",
                                           "model": "DXA-to-3D", "experimental": True}, allow_nan=False))


if __name__ == "__main__":
    main()
