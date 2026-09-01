"""无 pytest 环境的最小测试执行器。

用法：python tests/run_tests.py
（CI 与本地开发仍推荐 `pytest -q`，本脚本用于零依赖环境快速验证。）
"""

import os
import sys
import traceback
import importlib

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

MODULES = ["test_core", "test_retrieval", "test_export", "test_gateway", "test_channel", "test_transport", "test_clients", "test_capabilities", "test_sync_agent", "test_handoff"]


def main() -> int:
    tests = []
    for mod_name in MODULES:
        try:
            mod = importlib.import_module(mod_name)
        except ImportError as exc:
            print(f"FAIL  加载 {mod_name}: {exc}")
            return 1
        tests.extend(
            fn
            for name, fn in vars(mod).items()
            if name.startswith("test_") and callable(fn)
        )
    failed = 0
    for fn in tests:
        try:
            fn()
            print(f"PASS  {fn.__name__}")
        except Exception:
            failed += 1
            print(f"FAIL  {fn.__name__}")
            traceback.print_exc()
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
