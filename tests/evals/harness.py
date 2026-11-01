"""Runs a scripted conversation and checks it by code. No AI judge: a case passes or fails for a reason you can read."""
import json
import os
import re
import uuid
from dataclasses import dataclass, field

from emporio.graph import memory_graph, stream_turn


@dataclass
class Case:
    id: str
    turns: list[str]
    includes: list[str] = field(default_factory=list)  # regex, all must match the last reply
    excludes: list[str] = field(default_factory=list)  # regex, none may match any reply
    tools: list[str] = field(default_factory=list)     # must be called in the conversation
    forbidden_tools: list[str] = field(default_factory=list)
    arguments: dict = field(default_factory=dict)      # {tool: {argument: value}}
    now: str | None = None
    language: str = "pt"                               # interface language


@dataclass
class Run:
    replies: list[str]
    calls: list[tuple[str, dict]]
    outputs: list[dict]
    stats: list[dict]


def run_case(case: Case) -> Run:
    previous = os.environ.get("FIXED_NOW")
    if case.now:
        os.environ["FIXED_NOW"] = case.now
    try:
        graph = memory_graph()
        thread = f"eval-{case.id}"
        replies, calls, outputs, stats = [], [], [], []
        for turn in case.turns:
            for event in stream_turn(graph, thread, turn, language=case.language):
                if event["type"] == "tool_start":
                    calls.append((event["name"], json.loads(event["arguments"] or "{}")))
                elif event["type"] == "tool_end":
                    outputs.append(event["output"])
                elif event["type"] == "final":
                    replies.append(event["text"])
                    stats.append(event["stats"])
        return Run(replies, calls, outputs, stats)
    finally:
        if case.now and previous:
            os.environ["FIXED_NOW"] = previous


def failures(case: Case, run: Run) -> list[str]:
    problems = []
    last = run.replies[-1]
    everything = "\n".join(run.replies)
    called = [name for name, _ in run.calls]
    for pattern in case.includes:
        if not re.search(pattern, last, re.I):
            problems.append(f"missing /{pattern}/")
    for pattern in case.excludes:
        if re.search(pattern, everything, re.I):
            problems.append(f"forbidden /{pattern}/")
    for tool in case.tools:
        if tool not in called:
            problems.append(f"did not call {tool}")
    for tool in case.forbidden_tools:
        if tool in called:
            problems.append(f"called {tool}")
    for tool, expected in case.arguments.items():
        if not any(name == tool and all(args.get(k) == v for k, v in expected.items()) for name, args in run.calls):
            problems.append(f"{tool} without {expected}: {run.calls}")
    return problems
