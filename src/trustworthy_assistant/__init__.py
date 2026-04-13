from __future__ import annotations

from typing import Any

__all__ = ["TrustworthyAssistantApp", "build_app"]


def build_app(*args: Any, **kwargs: Any):
    from trustworthy_assistant.app import build_app as _build_app

    return _build_app(*args, **kwargs)


def __getattr__(name: str):
    if name == "TrustworthyAssistantApp":
        from trustworthy_assistant.app import TrustworthyAssistantApp

        return TrustworthyAssistantApp
    raise AttributeError(name)
