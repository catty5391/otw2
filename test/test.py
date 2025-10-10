# import pandas as pd
# import os
# import matplotlib.pyplot as plt
# print(os.getcwd())
# node = pd.read_csv("./output/Node_disp.out", header = None, sep = " ")
# x = node.iloc[11:,0]
# y = node.iloc[11:,1]


# plt.plot(x,y)
# plt.show()
import os
import subprocess

# 设置路径
input_folder = "C:/Users/admin/Desktop/机器学习矢量图"
output_folder = "C:/Users/admin/Desktop/机器学习png"
inkscape_path = "D:/inkscape/bin/inkscape.exe"  # Windows 默认路径，如果不在PATH中需指定

# 创建输出文件夹
os.makedirs(output_folder, exist_ok=True)

for filename in os.listdir(input_folder):
    if filename.lower().endswith('.emf'):
        input_path = os.path.join(input_folder, filename)
        output_path = os.path.join(output_folder, os.path.splitext(filename)[0] + '.svg')

        # 构建 Inkscape 命令
        # -o: 输出文件 (新版Inkscape)
        # --export-dpi: 设置导出DPI，数字越大越清晰，默认96。建议设为300或更高。
        command = [
            inkscape_path,
            input_path,
            "--export-dpi=1200",
            "--export-area-drawing",
            "-o", output_path
        ]

        try:
            # 执行命令
            subprocess.run(command, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            print(f"成功转换: {filename}")
        except subprocess.CalledProcessError as e:
            print(f"转换失败 {filename}: {e}")
