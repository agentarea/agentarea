# Sandbox runtime profiles

`package_install` is selected for every task as `allowed` or `locked` and is
carried in the sandbox execution contract. Runtime images are built with the
matching managed-environment mode:

| Task selection | Image build arg | Runtime manifest |
| --- | --- | --- |
| `allowed` | `MANAGED_ENVIRONMENT=mutable` | `managed_environment=mutable` |
| `locked` | `MANAGED_ENVIRONMENT=immutable` | `managed_environment=immutable` |

The control plane and activation service reject a request when its selection
does not match the assigned image. A deployment that serves both selections
must therefore operate separate mutable and immutable pools and route using
`runtime.package_install`; a single pool intentionally supports only its one
built profile. There is no downgrade from `locked` to `allowed`.

The immutable image removes pip from both the managed virtual environment and
the system Python installation, removes the bundled `ensurepip` and `venv`
bootstrap paths, removes Node package-manager entry points, makes
`/opt/runtime/venv` root-owned and read-only, and runs task commands as UID
10001. Kubernetes also selects locked pods with an exact profile label and
applies default-deny public egress; those pods can reach only DNS, the trusted
control plane, and configured S3 endpoints. Docker development intentionally
ships only the allowed profile and rejects locked requests.

`locked` means that task code cannot mutate the managed runtime or acquire
packages from public registries. It is not a source-code allowlist: arbitrary
code already supplied through the immutable task workspace remains executable,
and the task may write ordinary outputs inside its writable workspace.
