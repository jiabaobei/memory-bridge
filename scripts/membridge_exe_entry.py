"""PyInstaller 打包入口：把记忆桥打成便携 membridge.exe（借鉴 ncnn 的便携发布精神）。"""

import sys

from membridge.cli import main

if __name__ == "__main__":
    sys.exit(main())
