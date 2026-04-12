import os
from pathlib import Path
# import fluctuate_wind_simulate.wind_press.generate.waws as waws
# Try the correct import path based on your project structure:
import waws as waws


if __name__ == "__main__":
    # Batch settings
    base_speeds = [700]  # Reference wind speeds (v10) in m/s
    samples_per_speed = 10

    path = Path(os.getcwd())
    config_path = path / "fluctuate_wind_simulate/.config/wind_speed_generate_config.ini"
    output_root = path / "fluctuate_wind_simulate/static/wind_speed_generate"

    config = waws.ConfigData(config_path)

    for v10 in base_speeds:
        speed_dir = output_root / f"{int(v10)}mps"
        speed_dir.mkdir(parents=True, exist_ok=True)

        for sample_idx in range(1, samples_per_speed + 1):
            print(f"\n=== generating v10={v10} m/s, sample={sample_idx} ===")

            # update reference wind speed for this batch case
            config.v10 = float(v10)

            # different seed for each sample; keeps results reproducible across reruns
            seed = int(v10 * 1000 + sample_idx)

            sample_dir = speed_dir / f"sample_{sample_idx:02d}"
            sample_dir.mkdir(parents=True, exist_ok=True)

            gust = waws.GustWindField(config)
            gust.generate(mean=True, method="fft", seed=seed)
            gust.save(output_dir=str(sample_dir))
            gust.error(output_dir=str(sample_dir))