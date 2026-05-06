from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.append(str(PROJECT_ROOT))

from fluctuate_wind_simulate.opensees_simulate.wind_refactor_common import run_all_samples_serial


def main() -> None:
    parser = argparse.ArgumentParser(description="Run all wind samples serially in a single process.")
    parser.parse_args()
    results = run_all_samples_serial()
    print(f"serial run finished, total samples: {len(results)}")


if __name__ == "__main__":
    main()
