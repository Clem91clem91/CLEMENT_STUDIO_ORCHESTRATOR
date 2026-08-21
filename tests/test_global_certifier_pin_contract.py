from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WRAPPER = ROOT / "scripts" / "certify_global_p0.ps1"
LAUNCHER = ROOT / "scripts" / "certify_global_p0_v3.py"

NEW_P0_01_HEAD = "6a62a4215d53c56b2c27f71599d18f9faa2bbfac"
OLD_P0_01_HEAD = "583f1490063872d06c2866c5e08754c1e05cb77a"


def test_global_wrapper_uses_repinned_launcher() -> None:
    text = WRAPPER.read_text(encoding="utf-8")
    assert "certify_global_p0_v3.py" in text
    assert "certify_global_p0_v2.py" not in text


def test_repinned_launcher_overrides_only_p0_01_pin() -> None:
    text = LAUNCHER.read_text(encoding="utf-8")
    assert NEW_P0_01_HEAD in text
    assert OLD_P0_01_HEAD not in text
    assert 'EXPECTED_HEADS["P0-01"] = P0_01_CERTIFIED_HEAD' in text
    assert "return int(v2.main())" in text
