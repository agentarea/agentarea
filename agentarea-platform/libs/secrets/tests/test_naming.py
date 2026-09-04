"""Name rules for the secret catalog.

Two jobs live here and they pull in opposite directions. Platform code has been
minting secret names from owner ids since long before secrets were an entity,
so the catalog has to read those names back into an owner. And users are about
to get an API that names secrets itself, so the same module has to keep them
out of the space the platform already occupies.
"""

import pytest
from agentarea_secrets.naming import (
    RESERVED_PREFIXES,
    ReservedSecretNameError,
    SecretNameError,
    has_reserved_prefix,
    parse_managed_name,
    validate_user_secret_name,
)

INSTANCE_ID = "0b7f4a1e-2c3d-4e5f-8a9b-0c1d2e3f4a5b"
CONFIG_ID = "1c8e5b2f-3d4e-4f60-9bac-1d2e3f4a5b6c"


class TestParseManagedName:
    @pytest.mark.parametrize(
        ("name", "owner_type", "owner_id"),
        [
            (f"provider_config_{CONFIG_ID}", "provider_config", CONFIG_ID),
            (f"mcp_instance_{INSTANCE_ID}_API_KEY", "mcp_instance", INSTANCE_ID),
            (f"mcp_auth_cred:{CONFIG_ID}", "mcp_auth_config", CONFIG_ID),
            (f"channel_cred:telegram:{CONFIG_ID}", "trigger", CONFIG_ID),
            (f"wallet_creds_{CONFIG_ID}", "agent", CONFIG_ID),
            (f"openapi:{CONFIG_ID}:header:Authorization", "openapi_connection", CONFIG_ID),
            (f"task-input/{CONFIG_ID}/api_token", "task", CONFIG_ID),
            (f"a2a_push_token:{CONFIG_ID}:{INSTANCE_ID}", "task", CONFIG_ID),
        ],
    )
    def test_recognises_every_producer(self, name: str, owner_type: str, owner_id: str) -> None:
        owner = parse_managed_name(name)
        assert owner is not None, f"{name} was not recognised"
        assert (owner.owner_type, owner.owner_id) == (owner_type, owner_id)

    def test_env_name_containing_underscores_does_not_confuse_the_uuid(self) -> None:
        # The separator between instance id and env name is the same character
        # the env name itself uses, so only the fixed uuid width tells them apart.
        owner = parse_managed_name(f"mcp_instance_{INSTANCE_ID}_TELEGRAM_API_HASH")
        assert owner is not None
        assert owner.owner_id == INSTANCE_ID

    @pytest.mark.parametrize("config_id", ["my-config", "weird:id", "  ", "0"])
    def test_client_chosen_push_config_id_still_resolves_to_the_task(
        self, config_id: str
    ) -> None:
        # The A2A pushNotificationConfig id is whatever the client sends. If an
        # unparseable one were possible, that client could plant a name the
        # catalog backfill refuses to migrate — blocking every future deploy
        # with one API call. Only the task id has to be ours.
        owner = parse_managed_name(f"a2a_push_token:{CONFIG_ID}:{config_id}")
        assert owner is not None, f"config id {config_id!r} was not accepted"
        assert (owner.owner_type, owner.owner_id) == ("task", CONFIG_ID)

    def test_header_name_containing_a_colon_keeps_the_connection_id(self) -> None:
        owner = parse_managed_name(f"openapi:{CONFIG_ID}:header:X-Weird:Header")
        assert owner is not None
        assert owner.owner_id == CONFIG_ID

    @pytest.mark.parametrize(
        "name",
        [
            "openai-key",
            "my_secret",
            "provider_config_not-a-uuid",
            "mcp_instance_short_VAR",
            "",
        ],
    )
    def test_returns_none_for_anything_it_cannot_place(self, name: str) -> None:
        # A caller that cannot place a name must be able to tell, because the
        # backfill turns "unrecognised" into a failed migration rather than a
        # silent guess about who owns the row.
        assert parse_managed_name(name) is None


class TestHasReservedPrefix:
    """The backfill leans on this to tell two kinds of unparseable name apart.

    A name carrying a producer prefix that will not parse means a producer the
    parser has not been taught, and the migration must stop. A name carrying no
    producer prefix is a user's own — the agent toolset has always accepted an
    arbitrary name — and must migrate quietly as user-owned.
    """

    @pytest.mark.parametrize("prefix", RESERVED_PREFIXES)
    def test_true_for_a_producer_prefix_even_when_the_rest_is_unparseable(
        self, prefix: str
    ) -> None:
        name = f"{prefix}whatever-comes-next"
        assert has_reserved_prefix(name) is True
        assert parse_managed_name(name) is None

    @pytest.mark.parametrize("name", ["openai-key", "my_secret", "", "stripe-live"])
    def test_false_for_names_a_user_could_have_chosen(self, name: str) -> None:
        assert has_reserved_prefix(name) is False


class TestValidateUserSecretName:
    @pytest.mark.parametrize("name", ["openai-key", "stripe_live", "a1", "x" * 64])
    def test_accepts_slugs(self, name: str) -> None:
        validate_user_secret_name(name)

    @pytest.mark.parametrize(
        "name",
        ["", "a", "-leading", "trailing-", "Upper", "has space", "has/slash", "x" * 65],
    )
    def test_rejects_malformed(self, name: str) -> None:
        with pytest.raises(SecretNameError):
            validate_user_secret_name(name)

    @pytest.mark.parametrize("prefix", RESERVED_PREFIXES)
    def test_rejects_every_reserved_prefix(self, prefix: str) -> None:
        # (workspace_id, secret_name) is unique, so a user-chosen name that
        # collides with a managed one is not a new secret — set_secret updates
        # the existing row and the owning connection starts using whatever the
        # user typed.
        with pytest.raises(ReservedSecretNameError):
            validate_user_secret_name(f"{prefix}{INSTANCE_ID}")

    def test_reserved_check_runs_before_shape_check(self) -> None:
        # `mcp_auth_cred:<id>` fails the slug pattern too. Reporting it as a
        # malformed name would invite the user to "fix" it into a name that is
        # still reserved.
        with pytest.raises(ReservedSecretNameError):
            validate_user_secret_name(f"mcp_auth_cred:{CONFIG_ID}")

    def test_every_producer_prefix_is_actually_reserved(self) -> None:
        # Guards the pairing: a new producer added to parse_managed_name without
        # a matching reserved prefix would leave its names claimable by users.
        for name in (
            f"provider_config_{CONFIG_ID}",
            f"mcp_instance_{INSTANCE_ID}_API_KEY",
            f"mcp_auth_cred:{CONFIG_ID}",
            f"channel_cred:telegram:{CONFIG_ID}",
            f"wallet_creds_{CONFIG_ID}",
            f"openapi:{CONFIG_ID}:header:Authorization",
            f"task-input/{CONFIG_ID}/api_token",
            f"a2a_push_token:{CONFIG_ID}:{INSTANCE_ID}",
        ):
            with pytest.raises(ReservedSecretNameError):
                validate_user_secret_name(name)
