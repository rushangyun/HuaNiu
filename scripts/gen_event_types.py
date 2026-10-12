"""把 Python 的事件契约转成 TypeScript 类型。

为什么要有这个脚本：
    题目要求"前后端高度解耦"。但解耦不等于两端各写各的——
    总得有个地方对得上，不然改了后端忘了改前端，运行时才炸。

    与其手抄一遍类型（手抄的版本一定会漂移），不如让机器生成：
    Python 里的 dataclass 是唯一事实来源，TS 类型自动跟它对齐。

    这是很多成熟项目在用的做法（比如 tRPC、OpenAPI codegen），
    这里只是用最朴素的方式实现了一遍：解析 AST → 输出 .ts。

用法：
    python scripts/gen_event_types.py
    # 输出：web/src/types/events.ts

约定：改完 server/app/core/events.py 之后必须重跑一次。
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EVENTS_PY = ROOT / "server" / "app" / "core" / "events.py"
OUT_TS = ROOT / "web" / "src" / "types" / "events.ts"

# Python 注解 → TypeScript 类型
PY_TO_TS = {
    "str": "string",
    "int": "number",
    "float": "number",
    "bool": "boolean",
    "list": "unknown[]",
    "dict": "Record<string, unknown>",
    "Any": "unknown",
}


def ts_type(annotation: ast.AST) -> str:
    """把一条 Python 类型注解转成 TS 类型字符串。"""
    if isinstance(annotation, ast.Name):
        return PY_TO_TS.get(annotation.id, "unknown")

    if isinstance(annotation, ast.Subscript):
        base = getattr(annotation.value, "id", "")
        args = annotation.slice
        if base == "list" and isinstance(args, ast.Name):
            return f"{ts_type(args)}[]"
        if base == "list":
            return "unknown[]"
        if base == "dict":
            return "Record<string, unknown>"
        return "unknown"

    # `X | None` 写成 Union 时，ast 在 3.10+ 是 BinOp
    if isinstance(annotation, ast.BinOp):
        return ts_type(annotation.left)

    return "unknown"


def parse_events(source: str) -> tuple[list[tuple[str, str]], list[tuple[str, str, list[tuple[str, str, bool]]]]]:
    """解析出 (常量列表, 事件类列表)。

    常量：[(名字, 值)]
    事件类：[(类名, type值, [(字段名, ts类型, 是否可选)])]
    """
    tree = ast.parse(source)

    constants: list[tuple[str, str]] = []
    classes: list[tuple[str, str, list[tuple[str, str, bool]]]] = []

    for node in tree.body:
        # 模块级 `XXX = "xxx"` —— 事件类型常量
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Constant):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id.isupper():
                    constants.append((target.id, str(node.value.value)))
            continue

        if not isinstance(node, ast.ClassDef):
            continue

        # 只看带 @dataclass 的事件类；跳过基类 Event
        decorated = any(
            (isinstance(d, ast.Name) and d.id == "dataclass")
            or (isinstance(d, ast.Attribute) and d.attr == "dataclass")
            for d in node.decorator_list
        )
        if not decorated:
            continue

        fields: list[tuple[str, str, bool]] = []
        event_type = ""
        for stmt in node.body:
            if not isinstance(stmt, ast.AnnAssign) or not isinstance(stmt.target, ast.Name):
                continue
            name = stmt.target.id
            if name == "type":
                # type 字段要么有默认值（常量），要么是 field(default=XXX)
                if isinstance(stmt.value, ast.Constant):
                    event_type = str(stmt.value.value)
                elif isinstance(stmt.value, ast.Call):
                    for kw in stmt.value.keywords:
                        if kw.arg == "default" and isinstance(kw.value, ast.Name):
                            event_type = kw.value.id
                continue
            fields.append((name, ts_type(stmt.annotation), stmt.value is not None))

        if event_type:
            classes.append((node.name, event_type, fields))

    return constants, classes


def render(constants, classes) -> str:
    """拼出 TS 源码。"""
    lines = [
        "// 本文件由 scripts/gen_event_types.py 自动生成，**不要手改**。",
        "// 唯一事实来源是 server/app/core/events.py，改那里之后重跑生成脚本。",
        "",
        "// ---------------------------------------------------------------------------",
        "// 事件类型常量（与 Python 端同名同值）",
        "// ---------------------------------------------------------------------------",
        "",
    ]

    for name, value in constants:
        lines.append(f'export const {name} = "{value}" as const;')

    union = " | ".join(f'"{v}"' for _, v in constants) or "string"
    lines += ["", "export type EventType =", f"  | {union};", ""]

    lines += [
        "// ---------------------------------------------------------------------------",
        "// 事件结构",
        "// ---------------------------------------------------------------------------",
        "",
    ]

    type_names: list[str] = []
    for cls_name, event_type, fields in classes:
        const_name = next((n for n, v in constants if v == event_type), event_type.upper())
        lines.append(f"export interface {cls_name} {{")
        lines.append(f"  type: typeof {const_name};")
        for fname, ftype, optional in fields:
            lines.append(f"  {fname}{'?' if optional else ''}: {ftype};")
        lines.append("}")
        lines.append("")
        type_names.append(cls_name)

    alt = "\n  | ".join(type_names) if type_names else "never"
    lines += ["/** 后端可能推来的任意一种事件。 */", f"export type AgentEvent =\n  | {alt};", ""]

    return "\n".join(lines)


def main() -> None:
    import argparse

    ap = argparse.ArgumentParser(description="从 events.py 生成（或校验）前端 TS 类型")
    ap.add_argument(
        "--check",
        action="store_true",
        help="只校验 web/src/types/events.ts 是否与 events.py 一致，不写文件（给 CI 用）",
    )
    args = ap.parse_args()

    if not EVENTS_PY.is_file():
        print(f"找不到 {EVENTS_PY}", file=sys.stderr)
        sys.exit(1)

    constants, classes = parse_events(EVENTS_PY.read_text(encoding="utf-8"))
    if not classes:
        print("没解析到任何事件类，检查 events.py 的结构", file=sys.stderr)
        sys.exit(1)

    content = render(constants, classes)

    if args.check:
        current = OUT_TS.read_text(encoding="utf-8") if OUT_TS.is_file() else ""
        if current.strip() != content.strip():
            print(
                "❌ 事件契约已漂移：server/app/core/events.py 与 web/src/types/events.ts 不一致。\n"
                "   请运行：python scripts/gen_event_types.py",
                file=sys.stderr,
            )
            sys.exit(1)
        print(f"✅ 事件契约一致（常量 {len(constants)} 个，事件类 {len(classes)} 个）")
        return

    OUT_TS.parent.mkdir(parents=True, exist_ok=True)
    OUT_TS.write_text(content, encoding="utf-8")
    print(f"已生成 {OUT_TS.relative_to(ROOT)}")
    print(f"  常量 {len(constants)} 个，事件类 {len(classes)} 个：")
    for cls_name, event_type, _ in classes:
        print(f"    - {cls_name} (type={event_type})")


if __name__ == "__main__":
    main()
