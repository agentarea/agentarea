"""Unit tests for SkillService member management and topological sort."""

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from agentarea_agents.application.skill_service import SkillService, _topological_sort
from agentarea_agents.domain.skill_models import SkillMember


# ---------------------------------------------------------------------------
# Topological sort helper
# ---------------------------------------------------------------------------


class TestTopologicalSort:
    def test_empty_list(self):
        assert _topological_sort([]) == []

    def test_single_member_no_deps(self):
        sid = uuid4()
        m = MagicMock(spec=SkillMember)
        m.child_skill_id = sid
        m.dependencies = []
        result = _topological_sort([m])
        assert result == [sid]

    def test_linear_dependency_chain(self):
        a, b, c = uuid4(), uuid4(), uuid4()
        members = []
        for skill_id, deps in [(a, []), (b, [str(a)]), (c, [str(b)])]:
            m = MagicMock(spec=SkillMember)
            m.child_skill_id = skill_id
            m.dependencies = deps
            members.append(m)
        result = _topological_sort(members)
        assert result.index(a) < result.index(b) < result.index(c)

    def test_diamond_dependency(self):
        # a → b, a → c, b → d, c → d
        a, b, c, d = uuid4(), uuid4(), uuid4(), uuid4()
        specs = [
            (a, []),
            (b, [str(a)]),
            (c, [str(a)]),
            (d, [str(b), str(c)]),
        ]
        members = []
        for skill_id, deps in specs:
            m = MagicMock(spec=SkillMember)
            m.child_skill_id = skill_id
            m.dependencies = deps
            members.append(m)
        result = _topological_sort(members)
        assert result.index(a) < result.index(b)
        assert result.index(a) < result.index(c)
        assert result.index(b) < result.index(d)
        assert result.index(c) < result.index(d)

    def test_circular_dependency_raises(self):
        a, b = uuid4(), uuid4()
        members = []
        for skill_id, deps in [(a, [str(b)]), (b, [str(a)])]:
            m = MagicMock(spec=SkillMember)
            m.child_skill_id = skill_id
            m.dependencies = deps
            members.append(m)
        with pytest.raises(ValueError, match="Circular dependency"):
            _topological_sort(members)

    def test_ignores_unknown_deps(self):
        """Dependencies referencing skill IDs not in the member list are ignored."""
        a = uuid4()
        m = MagicMock(spec=SkillMember)
        m.child_skill_id = a
        m.dependencies = [str(uuid4())]  # references a non-member
        result = _topological_sort([m])
        assert result == [a]


# ---------------------------------------------------------------------------
# SkillService member methods
# ---------------------------------------------------------------------------


def _make_service():
    repo = AsyncMock()
    repo_factory = MagicMock()
    repo_factory.create_repository.return_value = repo
    user_ctx = MagicMock()
    svc = SkillService(repository_factory=repo_factory, user_context=user_ctx)
    return svc, repo


@pytest.mark.asyncio
class TestSkillServiceMembers:
    async def test_add_member_returns_skill_member(self):
        svc, repo = _make_service()
        parent_id = uuid4()
        child_id = uuid4()

        repo.get_members.return_value = []
        expected = SkillMember(parent_skill_id=parent_id, child_skill_id=child_id)
        repo.add_member.return_value = expected

        result = await svc.add_member(parent_id, child_id)
        assert result.child_skill_id == child_id
        assert result.parent_skill_id == parent_id

    async def test_add_member_self_reference_raises(self):
        svc, repo = _make_service()
        skill_id = uuid4()
        with pytest.raises(ValueError, match="itself"):
            await svc.add_member(skill_id, skill_id)

    async def test_add_member_cycle_detection(self):
        svc, repo = _make_service()
        parent_id = uuid4()
        child_a = uuid4()
        child_b = uuid4()

        # child_a depends on child_b; adding child_b that depends on child_a creates a cycle
        m = MagicMock(spec=SkillMember)
        m.child_skill_id = child_a
        m.dependencies = [str(child_b)]
        repo.get_members.return_value = [m]

        with patch(
            "agentarea_agents.application.skill_service._topological_sort",
            side_effect=ValueError("Circular dependency detected"),
        ):
            with pytest.raises(ValueError, match="cycle"):
                await svc.add_member(parent_id, child_b, dependencies=[str(child_a)])

    async def test_remove_member_returns_true_on_success(self):
        svc, repo = _make_service()
        repo.remove_member.return_value = True
        result = await svc.remove_member(uuid4(), uuid4())
        assert result is True

    async def test_remove_member_returns_false_if_not_found(self):
        svc, repo = _make_service()
        repo.remove_member.return_value = False
        result = await svc.remove_member(uuid4(), uuid4())
        assert result is False

    async def test_get_members_delegates_to_repo(self):
        svc, repo = _make_service()
        parent_id = uuid4()
        expected = [MagicMock(spec=SkillMember)]
        repo.get_members.return_value = expected
        result = await svc.get_members(parent_id)
        assert result is expected

    async def test_flatten_returns_ordered_ids(self):
        svc, repo = _make_service()
        a, b = uuid4(), uuid4()

        m_a = MagicMock(spec=SkillMember)
        m_a.child_skill_id = a
        m_a.dependencies = []

        m_b = MagicMock(spec=SkillMember)
        m_b.child_skill_id = b
        m_b.dependencies = [str(a)]

        repo.get_members.return_value = [m_a, m_b]

        result = await svc.flatten(uuid4())
        assert result.index(a) < result.index(b)

    async def test_flatten_empty_returns_empty(self):
        svc, repo = _make_service()
        repo.get_members.return_value = []
        result = await svc.flatten(uuid4())
        assert result == []
