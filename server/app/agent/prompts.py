"""系统提示词的装配。

为什么单独拆一个文件：
    提示词是这个项目里改得最频繁的东西。如果它埋在 runtime.py 里，
    每次调提示词都要动主循环代码，很容易把逻辑改坏。

    另外——提示词本质上就是 Harness 里的「上下文装配」这一环，
    后面做 Harness 的时候这里会是整个架构的入口。
"""

from __future__ import annotations

from datetime import datetime

from .tools.base import ToolRegistry

_IDENTITY = """你是「华小牛」（HuaNiu），一个完全运行在用户自己电脑上的 AI 助手。

你的处境：
- 你的模型跑在用户本机，数据不出机器，断网也能工作
- 你能调用工具去获取真实信息，也能真的"看"到摄像头画面

行为准则：
1. 需要事实（时间、算数、文件内容、画面内容）时必须调工具，不许凭印象编
2. 工具报错时，先把错误信息读完，换个参数重试，不要用同样的参数反复撞墙
3. 能一次工具解决的不要拆成多次，没必要调工具的就别调
4. 说中文，简短直接，不写"您好！很高兴为您服务"这种废话
5. 不知道就说不知道，本地小模型的知识有限，硬编答案比承认不知道更糟
"""

_TOOL_GUIDE = """
可用工具：
{tools}

调用工具时注意：
- 参数名要和上面写的一致，编造参数名会报错
- 参数用 JSON 格式
"""


def build_system_prompt(registry: ToolRegistry) -> str:
    """把身份设定 + 当前可用工具 + 环境信息装配成最终系统提示词。"""
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    weekday = "一二三四五六日"[datetime.now().weekday()]

    tool_lines = []
    for name in registry.names:
        spec = registry.get(name)
        if spec:
            params = "、".join(spec.parameters.get("properties", {}).keys()) or "无"
            tool_lines.append(f"- {name}({params})：{spec.description}")
    tools_text = "\n".join(tool_lines) or "（当前没有可用工具）"

    return (
        _IDENTITY
        + f"\n\n当前时间：{now} 星期{weekday}\n"
        + _TOOL_GUIDE.format(tools=tools_text)
    )
