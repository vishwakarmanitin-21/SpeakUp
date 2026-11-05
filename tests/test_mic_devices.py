"""Choosing the microphone (p58, after the 2026-11-05 silent-USB-mic incident)."""
from __future__ import annotations

import pytest

# MME-style list: the same physical mics also appear under other host APIs.
_DEVICES = [
    {"name": "Microsoft Sound Mapper - Input", "max_input_channels": 2, "hostapi": 0},
    {"name": "Microphone (2- Usb Audio Device", "max_input_channels": 1, "hostapi": 0},
    {"name": "Microphone Array (Realtek(R) Au", "max_input_channels": 2, "hostapi": 0},
    {"name": "Speakers (Realtek(R) Audio)", "max_input_channels": 0, "hostapi": 0},
    {"name": "Microphone (2- Usb Audio Device)", "max_input_channels": 1, "hostapi": 1},
]


@pytest.fixture
def fake_sd(monkeypatch):
    from src.audio import devices

    class FakeSd:
        class default:
            device = (1, 3)

        @staticmethod
        def query_devices(idx=None, kind=None):
            if kind == "input":
                return _DEVICES[1]
            return _DEVICES if idx is None else _DEVICES[idx]

    monkeypatch.setattr(devices, "sd", FakeSd)
    return devices


def test_lists_each_real_mic_once(fake_sd):
    assert fake_sd.list_input_devices() == [
        "Microphone (2- Usb Audio Device", "Microphone Array (Realtek(R) Au",
    ]


def test_empty_choice_means_windows_default(fake_sd):
    assert fake_sd.resolve_input_device("") is None


def test_exact_name_resolves_on_the_default_audio_api(fake_sd):
    assert fake_sd.resolve_input_device("Microphone Array (Realtek(R) Au") == 2
    assert fake_sd.resolve_input_device("Microphone (2- Usb Audio Device") == 1


def test_replugged_usb_mic_is_still_found(fake_sd):
    """Windows adds/drops the '2- ' prefix when a USB mic changes port."""
    assert fake_sd.resolve_input_device("Microphone (Usb Audio Device)") == 1


def test_default_audio_api_wins_over_an_exact_name_elsewhere(fake_sd, monkeypatch):
    """Same mic under WDM-KS with the exact saved name: still use the MME one."""
    devices = _DEVICES + [{"name": "Microphone (Usb Audio Device)", "max_input_channels": 1, "hostapi": 2}]
    monkeypatch.setattr(fake_sd.sd, "query_devices",
                        staticmethod(lambda idx=None, kind=None: devices if idx is None else devices[idx]))
    assert fake_sd.resolve_input_device("Microphone (Usb Audio Device)") == 1


def test_unplugged_mic_falls_back_to_the_default(fake_sd):
    assert fake_sd.resolve_input_device("Jabra Headset") is None


def test_verdict_words():
    from src.ui.components.mic_picker import MicPicker

    assert MicPicker.verdict_for(-84).startswith("Silent")      # the 2026-11-05 USB mic
    assert MicPicker.verdict_for(-45).startswith("Very quiet")
    assert MicPicker.verdict_for(-12).startswith("Hearing you")


def test_input_device_setting_defaults_to_windows_default(tmp_path, monkeypatch):
    import src.config as cfg_module
    from src.config import Config

    monkeypatch.setattr(cfg_module, "_PROJECT_ROOT", tmp_path)
    Config.reset()
    assert Config().input_device == ""
