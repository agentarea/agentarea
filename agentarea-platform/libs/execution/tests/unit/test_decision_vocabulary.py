"""The decide tool offers exactly the question types the decision model answers.

The SDK cannot import the llm domain, so the tool declares its own enum; this is
where the two meet, and where they must agree.
"""

from agentarea_agents_sdk.tools.decide_toolset import DecisionQuestionType as ToolQuestionType
from agentarea_llm.domain.media import DecisionQuestionType


def test_the_tool_and_the_model_share_one_question_vocabulary():
    assert {t.value for t in ToolQuestionType} == {t.value for t in DecisionQuestionType}
