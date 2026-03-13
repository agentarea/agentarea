from enum import StrEnum


class ContextType(StrEnum):
    WORKING = "working"
    FACTUAL = "factual"
    EPISODIC = "episodic"
    SEMANTIC = "semantic"


class ContextScope(StrEnum):
    TASK = "task"
    AGENT = "agent"
    GLOBAL = "global"
