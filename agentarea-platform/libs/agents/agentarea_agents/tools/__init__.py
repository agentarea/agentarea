"""Platform toolsets that agents use at runtime (worker-importable).

Relocated from apps/api so the Temporal worker (which cannot import
``agentarea_api``) can register them. apps/api keeps thin re-export shims.
"""
