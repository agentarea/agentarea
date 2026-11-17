# Sandbox runtime image

AgentArea builds one sandbox runtime image. Tasks and tools do not select an
image, network profile, or provider policy.

The image contains the pinned Python packages from `requirements.txt`, Python
and Node package managers, and the execution supervisor. Its build-time runtime
manifest records factual capabilities and the supervisor attestation. The
manager verifies that one manifest before admitting an external sandbox.

Isolation, provider image/template identity, and public internet access are
deployment configuration. Changing those settings creates a different data
plane deployment; it is not a per-task option.
