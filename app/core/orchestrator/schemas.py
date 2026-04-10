"""
Orchestrator 数据结构定义

包含 ExecutionPlan、ExecutionStep、JudgeResult、StreamEvent
"""
from dataclasses import dataclass, field
from typing import Dict, Any, List, Optional


@dataclass
class ExecutionStep:
    step_id: int
    goal: str
    strategy: str
    key_considerations: List[str] = field(default_factory=list)


@dataclass
class ExecutionPlan:
    overall_goal: str
    reasoning: str
    steps: List[ExecutionStep]
    tool_hints: List[str] = field(default_factory=list)


@dataclass
class JudgeResult:
    passed: bool
    reasons: List[str]
    failed_steps: List[int] = field(default_factory=list)


@dataclass
class StreamEvent:
    type: str
    node: str
    data: Dict[str, Any] = field(default_factory=dict)


__all__ = [
    "ExecutionStep",
    "ExecutionPlan",
    "JudgeResult",
    "StreamEvent",
]