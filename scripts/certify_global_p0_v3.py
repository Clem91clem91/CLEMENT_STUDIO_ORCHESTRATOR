from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


P0_01_CERTIFIED_HEAD = "6a62a4215d53c56b2c27f71599d18f9faa2bbfac"


def _load_v2():
    path = Path(__file__).with_name("certify_global_p0_v2.py")
    spec = importlib.util.spec_from_file_location("clement_global_certifier_v2_pinned", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"GLOBAL_V2_IMPORT_FAILED={path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def main() -> int:
    v2 = _load_v2()
    v2.legacy.EXPECTED_HEADS["P0-01"] = P0_01_CERTIFIED_HEAD
    actual = v2.legacy.EXPECTED_HEADS.get("P0-01")
    if actual != P0_01_CERTIFIED_HEAD:
        raise RuntimeError(
            f"P0_01_PIN_OVERRIDE_FAILED expected={P0_01_CERTIFIED_HEAD} actual={actual}"
        )
    print(f"P0_01_CERTIFIED_HEAD={P0_01_CERTIFIED_HEAD}")
    print("P0_01_PIN_OVERRIDE=PASS")
    return int(v2.main())


if __name__ == "__main__":
    raise SystemExit(main())
