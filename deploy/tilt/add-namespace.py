#!/usr/bin/env python3
"""Add a Kubernetes namespace to namespaced Helm-rendered resources."""

from __future__ import annotations

import sys

import yaml


CLUSTER_SCOPED_KINDS = {
    "ClusterRole",
    "ClusterRoleBinding",
    "CustomResourceDefinition",
    "GatewayClass",
    "Namespace",
    "Node",
    "PersistentVolume",
    "PriorityClass",
    "StorageClass",
}


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("usage: add-namespace.py <namespace>")

    namespace = sys.argv[1]
    docs = []
    for doc in yaml.safe_load_all(sys.stdin):
        if not doc:
            continue
        if doc.get("kind") not in CLUSTER_SCOPED_KINDS:
            metadata = doc.setdefault("metadata", {})
            metadata.setdefault("namespace", namespace)
        docs.append(doc)

    yaml.safe_dump_all(docs, sys.stdout, explicit_start=True, sort_keys=False)


if __name__ == "__main__":
    main()
