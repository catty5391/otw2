import os
import numpy as np
import scipy
# import fluctuate_wind_simulate.wind_press.generate.waws as waws
# Try the correct import path based on your project structure:
import waws as waws


if __name__ == "__main__":
    path = os.getcwd()
    config_path = os.path.join(path, "fluctuate_wind_simulate/.config/wind_speed_generate_config.ini")
    config = waws.ConfigData(config_path)

    # npts = 5
    # points = np.zeros((npts,4))
    # for i in range(1,npts+1):
    #     points[i-1, 0] = i
    #     points[i-1, 3] = i * 10

    # gust = GustWindField(config, points)
    gust = waws.GustWindField(config)
    gust.generate(mean=True, method="fft")
    gust.save()
    gust.error()