from __future__ import annotations

import json
from pathlib import Path

from ha_autoupgrade.config import AppConfig
from ha_autoupgrade.service import AutoUpgradeService


class FakeClient:
    def __init__(self) -> None:
        self.validated: list[dict] = []
        self.saved: list[dict] = []

    def validate_addon_options(self, slug: str, options: dict) -> dict:
        self.validated.append({"slug": slug, "options": dict(options)})
        return {"valid": True}

    def set_addon_options(self, slug: str, options: dict) -> dict:
        self.saved.append({"slug": slug, "options": dict(options)})
        return {"saved": True}


def test_import_configuration_merges_current_options(tmp_path: Path, monkeypatch) -> None:
    service = AutoUpgradeService.__new__(AutoUpgradeService)
    service.config = AppConfig.from_dict(
        {
            "check_interval_minutes": 90,
            "install_days": "sun",
            "install_hour": "03:00",
            "auto_install": True,
        },
        data_dir=tmp_path,
    )
    service.client = FakeClient()
    reloaded: list[AppConfig] = []
    service.reload_config = lambda config: reloaded.append(config)
    service._audit = lambda event, payload: None

    monkeypatch.setattr("ha_autoupgrade.service.IMPORT_DIR", tmp_path / "imports")

    result = service.import_configuration(
        {
            "options": {
                "install_days": "mon,wed,fri",
                "install_hour": "04:30",
            }
        }
    )

    validated_options = service.client.validated[0]["options"]
    saved_options = service.client.saved[0]["options"]
    imported_file = Path(result["path"])

    assert validated_options["check_interval_minutes"] == 90
    assert validated_options["auto_install"] is True
    assert validated_options["install_days"] == "mon,wed,fri"
    assert validated_options["install_hour"] == "04:30"
    assert saved_options == validated_options
    assert reloaded[0].install_days == ("mon", "wed", "fri")
    assert reloaded[0].install_hour == "04:30"
    assert json.loads(imported_file.read_text(encoding="utf-8"))["check_interval_minutes"] == 90
