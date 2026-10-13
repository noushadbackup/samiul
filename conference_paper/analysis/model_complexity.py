"""Parameter count and forward FLOPs of every model, built with the project's own
`build_model` (src/models/factory.py) at the input size in its config file.

Run:  python3 model_complexity.py /path/to/Deep-Learning-for-Alzheimers-MRI
(writes model_complexity.json; CPU only; MedicalNet weights are not downloaded because
pretrained weights do not change the parameter count)
"""
import json
import os
import sys

import torch
import yaml
from torch.utils.flop_counter import FlopCounterMode

RUNS = ["binary_cnn", "binary_resnet", "binary_hybrid_cnnvit", "binary_hybrid_swinvit",
        "3class_cnn", "3class_swin", "3class_vit"]


def main():
    repo = sys.argv[1]
    sys.path.insert(0, repo)
    from src.models.factory import build_model

    out = {}
    for run in RUNS:
        cfg = yaml.safe_load(open(os.path.join(repo, "configs", f"{run}.yaml")))
        cfg["pretrained"] = False
        nc = 2 if cfg["task"] == "binary" else 3
        model = build_model(cfg, nc).eval()
        params = sum(p.numel() for p in model.parameters())
        size = tuple(cfg["spatial_size"])
        x = torch.zeros(1, 1, *size)
        with torch.no_grad(), FlopCounterMode(display=False) as fc:
            model(x)
        out[run] = {"params_M": params / 1e6, "gflops": fc.get_total_flops() / 1e9,
                    "input": "x".join(map(str, size))}
        print(f"{run:24s} {params/1e6:7.2f} M params  {fc.get_total_flops()/1e9:8.1f} GFLOPs  input {size}")
    json.dump(out, open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "model_complexity.json"), "w"), indent=2)


if __name__ == "__main__":
    main()
