#!/usr/bin/env python3
"""Собирает .ipynb из читаемых исходников notebooks/*.py.

Зачем не писать .ipynb руками: это JSON, в котором код лежит списком строк —
его невозможно нормально читать и сравнивать в git. Поэтому автор пишет обычный
файл .py с разделителями ячеек, а этот скрипт превращает его в ноутбук.

Формат исходника:

    # %% [markdown]
    # # Заголовок
    # Обычный текст урока, каждая строка с решёткой.

    # %%
    print("это ячейка с кодом")

Запуск:  python3 scripts/build_notebooks.py [--check]
  --check ничего не пишет, а падает, если собранные ноутбуки устарели
          (нужно для CI: чтобы .ipynb в репозитории всегда соответствовал исходнику).
"""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE_DIR = ROOT / "notebooks"
TARGET_DIR = ROOT / "docs/books/labs"


def parse_cells(text):
    """Режет исходник на ячейки по строкам '# %%' и '# %% [markdown]'."""
    cells = []
    kind, buffer = None, []

    def flush():
        if kind is None:
            return
        body = "\n".join(buffer).strip("\n")
        if body.strip():
            cells.append((kind, body))

    for line in text.splitlines():
        if line.startswith("# %% [markdown]"):
            flush()
            kind, buffer = "markdown", []
        elif line.startswith("# %%"):
            flush()
            kind, buffer = "code", []
        elif kind == "markdown":
            # В markdown-ячейках строки закомментированы, снимаем решётку.
            buffer.append(line[2:] if line.startswith("# ") else line.lstrip("#"))
        elif kind == "code":
            buffer.append(line)
    flush()
    return cells


def build_notebook(cells):
    """Собирает структуру .ipynb. Вывод ячеек не сохраняем: он появится при запуске."""
    return {
        "cells": [
            {
                "cell_type": kind,
                "metadata": {},
                "source": [line + "\n" for line in body.split("\n")[:-1]] + [body.split("\n")[-1]],
                **({"outputs": [], "execution_count": None} if kind == "code" else {}),
            }
            for kind, body in cells
        ],
        "metadata": {
            "kernelspec": {"display_name": "Python 3", "language": "python", "name": "python3"},
            "language_info": {"name": "python", "version": "3.12"},
            "colab": {"provenance": []},
        },
        "nbformat": 4,
        "nbformat_minor": 5,
    }


def target_for(source):
    """notebooks/tema1-llm-osnovy__01_tokeny.py -> docs/books/labs/tema1-llm-osnovy/01_tokeny.ipynb"""
    folder, _, name = source.stem.partition("__")
    if not name:
        raise ValueError(f"{source.name}: имя должно быть вида <папка>__<название>.py")
    return TARGET_DIR / folder / f"{name}.ipynb"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="только проверить актуальность")
    args = parser.parse_args()

    sources = sorted(SOURCE_DIR.glob("*.py"))
    if not sources:
        print("Исходников ноутбуков не найдено", file=sys.stderr)
        return 1

    stale = []
    for source in sources:
        cells = parse_cells(source.read_text())
        if not cells:
            print(f"{source.name}: не найдено ни одной ячейки", file=sys.stderr)
            return 1

        # Код каждой ячейки должен быть синтаксически верным — иначе ученик
        # получит ошибку в самом неподходящем месте. Строки, начинающиеся с ! или %,
        # это команды Jupyter (например !pip install), а не Python — их пропускаем.
        for kind, body in cells:
            if kind == "code":
                python_only = "\n".join(
                    "" if line.lstrip().startswith(("!", "%")) else line
                    for line in body.split("\n")
                )
                try:
                    compile(python_only, source.name, "exec")
                except SyntaxError as error:
                    print(f"{source.name}: ошибка синтаксиса в ячейке — {error}", file=sys.stderr)
                    return 1

        target = target_for(source)
        content = json.dumps(build_notebook(cells), ensure_ascii=False, indent=1) + "\n"

        if args.check:
            if not target.exists() or target.read_text() != content:
                stale.append(target.relative_to(ROOT))
            continue

        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content)
        code_cells = sum(1 for kind, _ in cells if kind == "code")
        print(f"{target.relative_to(ROOT)}: ячеек {len(cells)} (кода {code_cells})")

    if stale:
        print("Ноутбуки устарели, запусти python3 scripts/build_notebooks.py:", file=sys.stderr)
        for path in stale:
            print(" -", path, file=sys.stderr)
        return 1

    if args.check:
        print(f"PASS: все {len(sources)} ноутбуков соответствуют исходникам")
    return 0


if __name__ == "__main__":
    sys.exit(main())
