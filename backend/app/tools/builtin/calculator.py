"""Safe calculator tool for the CrabClaw agent."""

from __future__ import annotations

import ast
import math
import operator


class CalculatorTool:
    """Evaluate simple math expressions safely using AST parsing.

    Supported: +, -, *, /, //, %, **, abs, round, min, max, sqrt,
    sin/cos/tan (math), log, log2, log10, pow, pi, e.
    """

    _ALLOWED_NODES = {
        ast.Expression, ast.Constant, ast.BinOp, ast.UnaryOp, ast.USub, ast.UAdd,
        ast.Call, ast.Name, ast.Load, ast.keyword,
        ast.Add, ast.Sub, ast.Mult, ast.Div, ast.FloorDiv, ast.Mod, ast.Pow,
    }

    _ALLOWED_FUNCS = {
        "abs": abs, "round": round, "min": min, "max": max,
        "sqrt": math.sqrt, "sin": math.sin, "cos": math.cos, "tan": math.tan,
        "log": math.log, "log2": math.log2, "log10": math.log10,
        "pow": pow, "pi": math.pi, "e": math.e,
    }

    _OP_MAP = {
        ast.Add: operator.add, ast.Sub: operator.sub,
        ast.Mult: operator.mul, ast.Div: operator.truediv,
        ast.FloorDiv: operator.floordiv, ast.Mod: operator.mod,
        ast.Pow: operator.pow,
    }

    def run(self, expression: str) -> str:
        text = (expression or "").strip()
        if not text:
            return "请输入要计算的表达式，例如 2 + 3 * 4"

        try:
            tree = ast.parse(text, mode="eval")
        except SyntaxError as exc:
            return f"表达式语法错误: {exc}"

        try:
            self._validate(tree)
        except ValueError as exc:
            return f"不安全的表达式: {exc}"

        try:
            result = self._eval_node(tree.body)
        except Exception as exc:
            return f"计算失败: {exc}"

        return f"{text} = {result}"

    def _validate(self, node: ast.AST) -> None:
        if type(node) not in self._ALLOWED_NODES:
            raise ValueError(f"不允许的节点类型: {type(node).__name__}")
        for child in ast.iter_child_nodes(node):
            self._validate(child)

    def _eval_node(self, node: ast.AST):
        if isinstance(node, ast.Constant):
            return node.value
        if isinstance(node, ast.BinOp):
            left = self._eval_node(node.left)
            right = self._eval_node(node.right)
            return self._OP_MAP[type(node.op)](left, right)
        if isinstance(node, ast.UnaryOp):
            operand = self._eval_node(node.operand)
            return -operand if isinstance(node.op, ast.USub) else +operand
        if isinstance(node, ast.Call):
            func = self._eval_node(node.func)
            if not callable(func):
                raise ValueError("不支持该函数调用")
            args = [self._eval_node(a) for a in node.args]
            return func(*args)
        if isinstance(node, ast.Name):
            name = node.id
            if name in self._ALLOWED_FUNCS:
                return self._ALLOWED_FUNCS[name]
            raise ValueError(f"未知变量: {name}")
        raise ValueError(f"不支持的节点: {type(node).__name__}")
