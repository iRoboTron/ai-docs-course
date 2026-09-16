"""Тесты по журналу случаев: каждый пойманный провал проверяется после каждой правки.

Запуск:  pytest -q shablony/tests/test_cases.py
Пока бот живёт в ноутбуке, эти тесты запускаются прямо в нём — сюда они переезжают
в модуле 7 вместе с кодом сервиса.
"""
import json
from pathlib import Path

import pytest

SLUCHAI = [json.loads(s) for s in (Path(__file__).parents[1] / "cases.jsonl").read_text().splitlines() if s.strip()]


def otvetit(vopros: str) -> str:
    """Заглушка: в проекте здесь вызывается настоящий бот."""
    raise NotImplementedError("подставь сюда своего бота")


def proverit(otvet: str, zhdem: str) -> bool:
    """«не знаю» засчитываем по смыслу, остальное — по вхождению ожидаемой строки."""
    otvet = otvet.lower()
    if zhdem == "не знаю":
        return "не зна" in otvet or "нет данных" in otvet or "не указан" in otvet
    return zhdem.lower() in otvet


@pytest.mark.parametrize("sluchay", SLUCHAI, ids=[s["id"] for s in SLUCHAI])
def test_sluchay(sluchay):
    otvet = otvetit(sluchay["vopros"])
    assert proverit(otvet, sluchay["zhdem"]), f"{sluchay['chto_ne_tak']}; получили: {otvet!r}"
