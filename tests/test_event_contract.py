"""事件契约一致性测试。

前后端解耦的全部前提是「契约不漂移」。手抄类型是解耦架构最常见的翻车方式，
所以这里强制：Python 的 events.py 是唯一事实来源，生成的 TS 必须与它一致。
"""

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "gen_event_types.py"


def test_event_contract_not_drifted():
    """跑 gen_event_types.py --check，契约漂移就失败。"""
    if not SCRIPT.is_file():
        raise AssertionError(f"找不到生成脚本: {SCRIPT}")
    proc = subprocess.run(
        [sys.executable, str(SCRIPT), "--check"],
        capture_output=True,
        text=True,
        cwd=str(ROOT),
    )
    assert proc.returncode == 0, (
        "事件契约已漂移：server/app/core/events.py 与 web/src/types/events.ts 不一致。\n"
        f"stdout: {proc.stdout}\nstderr: {proc.stderr}\n"
        "修复：python scripts/gen_event_types.py"
    )
