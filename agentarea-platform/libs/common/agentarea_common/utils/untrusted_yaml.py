"""Load YAML that a member or a public repository wrote, within bounds.

``yaml.safe_load`` builds no objects, but anchors, aliases and merge keys
still let a few hundred bytes expand exponentially in time and memory. Here
aliases and merge keys are refused outright, and composing stops at a node
budget; the text is refused above a byte budget before it is scanned.
"""

from typing import Any

import yaml

DEFAULT_MAX_BYTES = 1024 * 1024
_MERGE_TAG = "tag:yaml.org,2002:merge"


class UntrustedYamlError(yaml.YAMLError):
    """The YAML uses aliases or merge keys, or exceeds its budget."""


class _BoundedLoader(yaml.SafeLoader):
    def __init__(self, stream: str, max_nodes: int):
        super().__init__(stream)
        self._max_nodes = max_nodes
        self._nodes = 0

    def compose_node(self, parent: Any, index: Any) -> Any:
        if self.check_event(yaml.AliasEvent):
            raise UntrustedYamlError("YAML aliases are not accepted here")
        self._nodes += 1
        if self._nodes > self._max_nodes:
            raise UntrustedYamlError(f"YAML holds at most {self._max_nodes} nodes here")
        return super().compose_node(parent, index)

    def flatten_mapping(self, node: Any) -> None:
        if any(key.tag == _MERGE_TAG for key, _value in node.value):
            raise UntrustedYamlError("YAML merge keys are not accepted here")
        super().flatten_mapping(node)


def load_untrusted_yaml(text: str, *, max_nodes: int, max_bytes: int = DEFAULT_MAX_BYTES) -> Any:
    """The single document in ``text``; ``UntrustedYamlError`` past a bound.

    CPU-bound in proportion to the budgets: a caller on an event loop with a
    large budget runs it in a worker thread.
    """
    if len(text.encode("utf-8")) > max_bytes:
        raise UntrustedYamlError(f"YAML is larger than {max_bytes} bytes")
    loader = _BoundedLoader(text, max_nodes)
    try:
        return loader.get_single_data()
    finally:
        loader.dispose()
