"""Event-bus transport adapters (ADR-0018).

Each adapter implements the broker-neutral ports from
``agentarea_common.events.ports`` for one backend. Redis Streams ships in OSS;
Kafka/NATS adapters are registered the same way (entry points) by enterprise.
"""
