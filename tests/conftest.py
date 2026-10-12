"""pytest 公共配置：让测试能 import server/app 下的模块。

测试放在仓库根目录的 tests/ 里，而后端代码在 server/ 下，
所以这里把 server/ 加进 sys.path，测试文件就能直接 `from app...` 导入。
"""

import sys
from pathlib import Path

SERVER_DIR = Path(__file__).resolve().parents[1] / "server"
if str(SERVER_DIR) not in sys.path:
    sys.path.insert(0, str(SERVER_DIR))
