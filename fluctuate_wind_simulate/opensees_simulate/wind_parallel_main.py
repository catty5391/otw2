from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.append(str(PROJECT_ROOT))

from fluctuate_wind_simulate.opensees_simulate.wind_refactor_common import run_all_samples_parallel


def main() -> None:
    parser = argparse.ArgumentParser(description="Run wind samples in parallel with multiple Python processes.")
    parser.add_argument("--max-workers", type=int, default=0, help="Number of worker processes. Use 0 to auto-match the number of wind speeds.")
    args = parser.parse_args()

    results = run_all_samples_parallel(max_workers=args.max_workers)
    print(f"parallel run finished, total samples: {len(results)}")


if __name__ == "__main__":
    main()
