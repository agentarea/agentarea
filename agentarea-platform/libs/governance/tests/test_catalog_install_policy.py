"""Which registries a workspace may install catalog items from (ADR-0044).

Install rules are ordinary policy rules on a ``registry:<id>`` or
``registry_trust:<level>`` target. With none, every install is allowed, as with
every other policy decision; a deny wins; an allow rule turns its layer into an
allowlist.
"""

from uuid import uuid4

import pytest
from agentarea_common.auth.context import UserContext
from agentarea_common.base.models import BaseModel
from agentarea_governance.application.catalog_install import authorize_catalog_install
from agentarea_governance.domain.rules import (
    PolicyEffect,
    PolicyRule,
    PolicySubjectType,
    assert_enforceable,
    decide_catalog_install,
    rules_to_document,
)
from agentarea_governance.domain.policies import PolicyDocument
from agentarea_governance.infrastructure.orm import PolicyRuleORM
from agentarea_governance.infrastructure.repository import PolicyRuleRepository
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

REGISTRY = str(uuid4())
OTHER_REGISTRY = str(uuid4())


def _rule(
    target: str,
    effect: PolicyEffect,
    subject_type: PolicySubjectType = PolicySubjectType.WORKSPACE,
    subject_id: str = "ws-a",
) -> PolicyRule:
    return PolicyRule(
        subject_type=subject_type, subject_id=subject_id, target=target, effect=effect
    )


class TestDecision:
    def test_no_rules_allow(self):
        assert decide_catalog_install([], registry_id=REGISTRY, trust="community").allowed

    def test_a_deny_on_the_registry_blocks(self):
        decision = decide_catalog_install(
            [_rule(f"registry:{REGISTRY}", PolicyEffect.DENY)],
            registry_id=REGISTRY,
            trust="official",
        )
        assert not decision.allowed
        assert REGISTRY in decision.reason

    def test_a_deny_on_the_trust_level_blocks(self):
        rules = [_rule("registry_trust:community", PolicyEffect.DENY)]
        assert not decide_catalog_install(rules, registry_id=REGISTRY, trust="community").allowed
        assert decide_catalog_install(rules, registry_id=REGISTRY, trust="official").allowed

    def test_an_allow_rule_makes_its_layer_an_allowlist(self):
        rules = [_rule("registry_trust:official", PolicyEffect.ALLOW)]
        assert decide_catalog_install(rules, registry_id=REGISTRY, trust="official").allowed
        assert not decide_catalog_install(rules, registry_id=REGISTRY, trust="community").allowed

    def test_a_matching_allow_on_the_registry_passes_the_allowlist(self):
        rules = [
            _rule("registry_trust:official", PolicyEffect.ALLOW),
            _rule(f"registry:{REGISTRY}", PolicyEffect.ALLOW),
        ]
        assert decide_catalog_install(rules, registry_id=REGISTRY, trust="private").allowed
        assert not decide_catalog_install(
            rules, registry_id=OTHER_REGISTRY, trust="private"
        ).allowed

    def test_deny_beats_allow(self):
        rules = [
            _rule("registry_trust:community", PolicyEffect.ALLOW),
            _rule(f"registry:{REGISTRY}", PolicyEffect.DENY),
        ]
        assert not decide_catalog_install(rules, registry_id=REGISTRY, trust="community").allowed

    def test_a_user_layer_only_tightens(self):
        rules = [
            _rule("registry_trust:community", PolicyEffect.ALLOW),
            _rule(
                "registry_trust:official",
                PolicyEffect.ALLOW,
                PolicySubjectType.USER,
                "user-a",
            ),
        ]
        # Each layer is its own allowlist: the user's does not widen the workspace's.
        assert not decide_catalog_install(rules, registry_id=REGISTRY, trust="official").allowed
        assert not decide_catalog_install(rules, registry_id=REGISTRY, trust="community").allowed

    def test_disabled_and_unrelated_rules_are_ignored(self):
        disabled = _rule(f"registry:{REGISTRY}", PolicyEffect.DENY)
        disabled.enabled = False
        rules = [disabled, _rule("tool:send_email", PolicyEffect.DENY)]
        assert decide_catalog_install(rules, registry_id=REGISTRY, trust="community").allowed


class TestValidation:
    @pytest.mark.parametrize(
        "target",
        [
            f"registry:{REGISTRY}",
            "registry:github",
            "registry_trust:official",
            "registry_trust:private",
        ],
    )
    @pytest.mark.parametrize("effect", [PolicyEffect.ALLOW, PolicyEffect.DENY])
    def test_install_rules_are_enforceable(self, target, effect):
        assert_enforceable(_rule(target, effect))

    @pytest.mark.parametrize(
        "target",
        ["registry:not-a-uuid", "registry:*", "registry_trust:famous", "registry_trust:*"],
    )
    def test_a_target_that_names_no_registry_or_level_is_refused(self, target):
        with pytest.raises(ValueError):
            assert_enforceable(_rule(target, PolicyEffect.DENY))

    def test_an_agent_subject_is_refused(self):
        with pytest.raises(ValueError, match="workspace or a user"):
            assert_enforceable(
                _rule(
                    "registry_trust:community",
                    PolicyEffect.DENY,
                    PolicySubjectType.AGENT,
                    str(uuid4()),
                )
            )

    @pytest.mark.parametrize("effect", [PolicyEffect.CAP, PolicyEffect.APPROVAL])
    def test_other_effects_are_refused(self, effect):
        with pytest.raises(ValueError):
            assert_enforceable(_rule("registry_trust:community", effect))

    def test_install_rules_stay_out_of_the_runtime_document(self):
        assert rules_to_document(
            [_rule("registry_trust:community", PolicyEffect.DENY)]
        ) == PolicyDocument()


@pytest.fixture
async def session_factory():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(
            lambda sync_conn: BaseModel.metadata.create_all(
                sync_conn, tables=[PolicyRuleORM.__table__]
            )
        )
    try:
        yield async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    finally:
        await engine.dispose()


async def test_the_stored_rules_of_the_workspace_and_the_installer_decide(session_factory):
    context = UserContext(user_id="user-a", workspace_id="ws-a")
    async with session_factory() as session:
        repo = PolicyRuleRepository(session, context)
        await repo.create(_rule("registry_trust:community", PolicyEffect.DENY))
        await repo.create(
            _rule(f"registry:{REGISTRY}", PolicyEffect.DENY, PolicySubjectType.USER, "user-b")
        )
        await session.commit()

        denied = await authorize_catalog_install(
            session, context, registry_id=REGISTRY, trust="community"
        )
        allowed = await authorize_catalog_install(
            session, context, registry_id=REGISTRY, trust="official"
        )

    assert not denied.allowed
    # user-b's rule is not the installer's.
    assert allowed.allowed


async def test_another_workspaces_rules_do_not_apply(session_factory):
    async with session_factory() as session:
        other = UserContext(user_id="user-a", workspace_id="ws-b")
        await PolicyRuleRepository(session, other).create(
            _rule("registry_trust:community", PolicyEffect.DENY, subject_id="ws-b")
        )
        await session.commit()

        decision = await authorize_catalog_install(
            session,
            UserContext(user_id="user-a", workspace_id="ws-a"),
            registry_id=REGISTRY,
            trust="community",
        )

    assert decision.allowed
