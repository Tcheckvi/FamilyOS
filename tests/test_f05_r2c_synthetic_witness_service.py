from __future__ import annotations

import importlib.util
import json
import subprocess
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
RUNNER_PATH = REPO_ROOT / "scripts" / "f05_r2c_synthetic_witness_service.py"


def _load_runner() -> ModuleType:
    spec = importlib.util.spec_from_file_location("f05_r2c_synthetic_witness_service", RUNNER_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


runner = _load_runner()


def _set_interface_result(
    monkeypatch: pytest.MonkeyPatch,
    *,
    stdout: str,
    returncode: int = 0,
) -> None:
    def fake_run(*_args: Any, **_kwargs: Any) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(
            args=["/usr/sbin/ipconfig", "getifaddr", "en0"],
            returncode=returncode,
            stdout=stdout,
            stderr="",
        )

    monkeypatch.setattr(runner.subprocess, "run", fake_run)


def _valid_policy() -> dict[str, object]:
    return {
        "bind_strategy": "current_interface_ipv4",
        "network_interface": "en0",
        "bind_port": 9443,
        "server_hostname": "synthetic-witness.local",
    }


def test_accepts_valid_current_non_loopback_ipv4(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_interface_result(monkeypatch, stdout="192.0.2.42\n")
    assert runner.current_interface_ipv4("en0") == "192.0.2.42"


def test_rejects_missing_interface_ipv4(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_interface_result(monkeypatch, stdout="", returncode=1)
    with pytest.raises(RuntimeError):
        runner.current_interface_ipv4("en0")


def test_rejects_empty_interface_output(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_interface_result(monkeypatch, stdout=" \n")
    with pytest.raises(RuntimeError):
        runner.current_interface_ipv4("en0")


def test_rejects_malformed_address(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_interface_result(monkeypatch, stdout="300.1.1.1\n")
    with pytest.raises(RuntimeError):
        runner.current_interface_ipv4("en0")


def test_rejects_ipv6_for_ipv4_only_profile(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_interface_result(monkeypatch, stdout="2001:db8::1\n")
    with pytest.raises(RuntimeError):
        runner.current_interface_ipv4("en0")


@pytest.mark.parametrize("address", ["127.0.0.1", "0.0.0.0", "224.0.0.1"])
def test_rejects_unsafe_ipv4_classes(
    monkeypatch: pytest.MonkeyPatch,
    address: str,
) -> None:
    _set_interface_result(monkeypatch, stdout=f"{address}\n")
    with pytest.raises(RuntimeError):
        runner.current_interface_ipv4("en0")


def test_accepts_current_interface_ipv4_strategy() -> None:
    config = _valid_policy()
    runner.validate_network_policy(config)


@pytest.mark.parametrize("strategy", ["static", "bind_ip", "", None])
def test_rejects_unsupported_or_static_strategy(strategy: object) -> None:
    config = _valid_policy()
    config["bind_strategy"] = strategy
    with pytest.raises(RuntimeError):
        runner.validate_network_policy(config)


def test_rejects_any_legacy_bind_ip_key() -> None:
    config = _valid_policy()
    config["bind_ip"] = "192.0.2.10"
    with pytest.raises(RuntimeError):
        runner.validate_network_policy(config)


def test_rejects_empty_interface() -> None:
    config = _valid_policy()
    config["network_interface"] = ""
    with pytest.raises(RuntimeError):
        runner.validate_network_policy(config)


@pytest.mark.parametrize("port", [0, 65536, True, "9443"])
def test_rejects_invalid_port(port: object) -> None:
    config = _valid_policy()
    config["bind_port"] = port
    with pytest.raises(RuntimeError):
        runner.validate_network_policy(config)


def test_rejects_empty_hostname() -> None:
    config = _valid_policy()
    config["server_hostname"] = ""
    with pytest.raises(RuntimeError):
        runner.validate_network_policy(config)


def test_schema_version_two_is_required(tmp_path: Path) -> None:
    path = tmp_path / "service.json"
    path.write_text(json.dumps({"schema_version": 1}), encoding="utf-8")
    path.chmod(0o600)
    with pytest.raises(RuntimeError):
        runner.load_config(path)


def test_authoritative_runner_contains_no_historical_lan_addresses() -> None:
    source = RUNNER_PATH.read_text(encoding="utf-8")
    assert "192.168.1.182" not in source
    assert "192.168.1.192" not in source


def test_bind_ip_is_not_accepted_by_network_policy() -> None:
    config = _valid_policy()
    config["bind_ip"] = None
    with pytest.raises(RuntimeError):
        runner.validate_network_policy(config)


def test_server_hostname_is_independent_from_dynamic_bind_address(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = _valid_policy()
    config["server_hostname"] = "witness.example.test"
    runner.validate_network_policy(config)

    _set_interface_result(monkeypatch, stdout="198.51.100.42\n")
    selected = runner.current_interface_ipv4(str(config["network_interface"]))

    assert selected == "198.51.100.42"
    assert config["server_hostname"] == "witness.example.test"
    assert config["server_hostname"] != selected
