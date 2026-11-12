"""Stable kernel selection shared by commands, tools and the management page."""

try:
    from .engine import calculate as calculate_legacy
    from .engine import infer_root
    from .engine_v2 import CONVENTIONS, VERSION, calculate_v2
except ImportError:
    from engine import calculate as calculate_legacy
    from engine import infer_root
    from engine_v2 import CONVENTIONS, VERSION, calculate_v2

KERNELS = (
    {
        "id": "legacy_v1",
        "name": "经典内核 v1",
        "version": "1.0",
        "description": "原有五位环形计分，保留成、败及三次死卦规则。",
    },
    {
        "id": "document_v2",
        "name": "资料推演 v2",
        "version": VERSION,
        "description": "补齐五行、阴阳变化及逐轮生克；资料不足的组合明确待定。",
        "conventions": list(CONVENTIONS),
    },
)


def calculate(question, numbers, root_element=None, *, kernel_id="legacy_v1"):
    if kernel_id == "legacy_v1":
        return calculate_legacy(question, numbers, root_element)
    if kernel_id == "document_v2":
        return calculate_v2(question, numbers, root_element or infer_root(question))
    raise ValueError("未知计算内核，请重新选择。")
