"""The registry must report declarations under the names the PDP judges.

``@toolset(namespace="agentarea/shell", requires_user_confirmation=True)`` is a
statement about a toolset, but policy decides per tool call — and the name it
sees is ``shell_bash``. A declaration exported as ``agentarea/shell`` would match
nothing and gate nothing, which is how the flag stayed decorative.
"""

from agentarea_agents_sdk.tools.code_tools_loader import tools_requiring_confirmation
from agentarea_agents_sdk.tools.shell_toolset import ShellToolset


def test_shell_is_declared_under_the_name_the_gate_judges():
    assert "shell_bash" in tools_requiring_confirmation()


def test_the_namespace_is_not_what_gets_exported():
    declared = tools_requiring_confirmation()

    assert "agentarea/shell" not in declared
    assert "shell" not in declared


def test_derived_names_match_what_the_toolset_actually_advertises():
    # The derivation inspects classes rather than instantiating them, so it can
    # drift from the real advertisement. Pin it against the live definitions.
    advertised = {definition.name for definition in ShellToolset().get_tool_definitions()}

    assert set(tools_requiring_confirmation()) & advertised == {"shell_bash"}


def test_a_toolset_that_declares_nothing_is_absent():
    declared = set(tools_requiring_confirmation())

    assert not any(name.startswith("completion") for name in declared)
