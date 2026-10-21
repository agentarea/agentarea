"""Load YAML that a member or a public repository wrote, within bounds.

``yaml.safe_load`` builds no objects, but anchors, aliases and merge keys
still let a few hundred bytes expand exponentially in time and memory. Here
aliases and merge keys are refused outright, and composing stops at a node
and a nesting budget; the text is refused above a byte budget before it is
scanned.
"""

from typing import Any

import yaml

DEFAULT_MAX_BYTES = 1024 * 1024
# The composer recurses a few frames per level; past this the error would be
# a RecursionError that no caller classifies.
DEFAULT_MAX_DEPTH = 64
_MERGE_TAG = "tag:yaml.org,2002:merge"


class UntrustedYamlError(yaml.YAMLError):
    """The YAML uses aliases or merge keys, or exceeds its budget."""


class _BoundedLoader(yaml.SafeLoader):
    def __init__(self, stream: str, max_nodes: int, max_depth: int):
        super().__init__(stream)
        self._max_nodes = max_nodes
        self._max_depth = max_depth
        self._nodes = 0
        self._depth = 0

    def compose_node(self, parent: Any, index: Any) -> Any:
        if self.check_event(yaml.AliasEvent):
            raise UntrustedYamlError("YAML aliases are not accepted here")
        self._nodes += 1
        if self._nodes > self._max_nodes:
            raise UntrustedYamlError(f"YAML holds at most {self._max_nodes} nodes here")
        self._depth += 1
        if self._depth > self._max_depth:
            raise UntrustedYamlError(f"YAML is nested deeper than {self._max_depth} levels")
        try:
            return super().compose_node(parent, index)
        finally:
            self._depth -= 1

    def flatten_mapping(self, node: Any) -> None:
        if any(key.tag == _MERGE_TAG for key, _value in node.value):
            raise UntrustedYamlError("YAML merge keys are not accepted here")
        super().flatten_mapping(node)


class _TextTimestampLoader(_BoundedLoader):
    pass


_TextTimestampLoader.add_constructor(
    "tag:yaml.org,2002:timestamp", _TextTimestampLoader.construct_yaml_str
)


def load_untrusted_yaml(
    text: str,
    *,
    max_nodes: int,
    max_bytes: int = DEFAULT_MAX_BYTES,
    max_depth: int = DEFAULT_MAX_DEPTH,
    timestamps_as_text: bool = False,
) -> Any:
    """The single document in ``text``; ``UntrustedYamlError`` past a bound.

    CPU-bound in proportion to the budgets: a caller on an event loop with a
    large budget runs it in a worker thread. ``timestamps_as_text`` keeps an
    unquoted date as its source text, for documents stored as JSON.
    """
    if len(text.encode("utf-8", "surrogatepass")) > max_bytes:
        raise UntrustedYamlError(f"YAML is larger than {max_bytes} bytes")
    loader_class = _TextTimestampLoader if timestamps_as_text else _BoundedLoader
    loader = loader_class(text, max_nodes, max_depth)
    try:
        return loader.get_single_data()
    finally:
        loader.dispose()
