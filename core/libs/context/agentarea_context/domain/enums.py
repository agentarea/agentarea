from enum import Enum


class ContextType(str, Enum):
    WORKING = "working"
    FACTUAL = "factual"
    EPISODIC = "episodic"
    SEMANTIC = "semantic"


class ContextScope(str, Enum):
    TASK = "task"
    AGENT = "agent"
    GLOBAL = "global"
