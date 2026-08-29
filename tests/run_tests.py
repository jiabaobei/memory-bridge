"""无 pytest 环境的最小测试执行器。

用法：python tests/run_tests.py
（CI 与本地开发仍推荐 `pytest -q`，本脚本用于零依赖环境快速验证。）
"""

import os
import sys
import traceback

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import test_core  # noqa: E402


def main() -> int:
    tests = [
        fn
        for name, fn in vars(test_core).items()
        if name.startswith("test_") and callable(fn)
    ]
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
