#!/usr/bin/env python3
"""Собирает firmware/esp32/pi30.py из collector/solar_monitor/pi30.py.

MicroPython не переваривает часть синтаксиса аннотаций (`dict[str, dict]`,
`bytes | None`), поэтому аннотации вырезаются через ast. Логика остаётся ровно
одной: изменения в серверном парсере попадают в прошивку пересборкой, а тест
test_firmware.py сверяет результаты обоих файлов на одних и тех же кадрах.
"""
from __future__ import annotations

import ast
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
SRC = ROOT / "collector" / "solar_monitor" / "pi30.py"
DST = ROOT / "firmware" / "esp32" / "pi30.py"

HEADER = '''"""PI30-парсеры для прошивки ESP32.

СГЕНЕРИРОВАНО tools/make_firmware_pi30.py из collector/solar_monitor/pi30.py —
руками не править. Логика идентична серверной (проверяется тестом
collector/tests/test_firmware.py).
"""
'''


class StripAnnotations(ast.NodeTransformer):
    def _strip_args(self, args: ast.arguments):
        for a in list(args.args) + list(args.kwonlyargs) + list(getattr(args, "posonlyargs", [])):
            a.annotation = None
            a.type_comment = None
        for a in (args.vararg, args.kwarg):
            if a is not None:
                a.annotation = None
        args.returns = None

    def visit_FunctionDef(self, node):
        self.generic_visit(node)
        self._strip_args(node.args)
        return node

    def visit_AsyncFunctionDef(self, node):
        return self.visit_FunctionDef(node)

    def visit_AnnAssign(self, node):
        self.generic_visit(node)
        if node.value is None:
            return None
        return ast.Assign(targets=[node.target], value=node.value, lineno=node.lineno,
                          col_offset=node.col_offset)


def main() -> int:
    src = SRC.read_text()
    tree = ast.parse(src)
    # `from __future__ import annotations` в MicroPython не нужен и не мешает, но
    # убираем -- меньше сюрпризов на старых сборках.
    tree.body = [n for n in tree.body
                 if not (isinstance(n, ast.ImportFrom) and n.module == "__future__")]
    tree = StripAnnotations().visit(tree)
    ast.fix_missing_locations(tree)
    out = HEADER + ast.unparse(tree) + "\n"
    DST.write_text(out)
    print(f"{DST.relative_to(ROOT)}: {len(out.splitlines())} строк "
          f"(из {SRC.relative_to(ROOT)})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
