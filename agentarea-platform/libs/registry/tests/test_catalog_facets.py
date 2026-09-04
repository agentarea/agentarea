"""Facet derivation for catalog browsing.

`derive_facets` is the server-side twin of the webapp's `normalize()`
(agentarea-webapp/src/app/(main)/bundles/components/catalog-data.ts): it pulls
the browsable dimensions -- category, sort key, featured flag -- out of a
registry item's heterogeneous spec/tags so the catalog can be filtered, sorted
and faceted in SQL instead of on a partially-loaded client list.

Pure function, no DB.
"""

from agentarea_registry.application.catalog_facets import derive_facets


class TestCategory:
    def test_bundles_read_category_from_spec_metadata(self):
        f = derive_facets("bundles", name="Support Desk", spec={"metadata": {"category": "support"}}, tags=[])
        assert f.category == "support"

    def test_agents_use_their_first_tag(self):
        f = derive_facets("agents", name="Triage", spec={}, tags=["support", "email"])
        assert f.category == "support"

    def test_skills_read_the_category_prefixed_tag(self):
        f = derive_facets(
            "skills", name="pdf-fill", spec={}, tags=["repo:anthropics-claude-code", "category:other"]
        )
        assert f.category == "other"

    def test_mcp_servers_read_the_curated_metadata_key(self):
        f = derive_facets(
            "mcp_servers",
            name="Telegram",
            spec={"raw_spec": {"metadata": {"agentarea:category": "messaging"}}},
            tags=[],
        )
        assert f.category == "messaging"

    def test_missing_category_is_none(self):
        assert derive_facets("bundles", name="X", spec={}, tags=[]).category is None
        assert derive_facets("agents", name="X", spec={}, tags=[]).category is None
        assert derive_facets("skills", name="X", spec={}, tags=["repo:a"]).category is None
        assert derive_facets("mcp_servers", name="X", spec={}, tags=[]).category is None

    def test_empty_string_category_is_none(self):
        # `str()` on the client treats "" as absent; the facet must agree or the
        # sidebar grows a nameless bucket nothing can select.
        f = derive_facets("bundles", name="X", spec={"metadata": {"category": ""}}, tags=[])
        assert f.category is None

    def test_non_string_category_is_none(self):
        f = derive_facets("bundles", name="X", spec={"metadata": {"category": 7}}, tags=[])
        assert f.category is None

    def test_types_without_a_category_dimension_get_none(self):
        assert derive_facets("llm_models", name="gpt-4o", spec={}, tags=["openai"]).category is None


class TestSortKey:
    def test_is_case_folded_so_ordering_ignores_case(self):
        assert derive_facets("agents", name="Zapier", spec={}, tags=[]).sort_key == "zapier"

    def test_bundles_prefer_display_name(self):
        f = derive_facets(
            "bundles", name="support-desk", spec={"display_name": "Support Desk", "name": "sd"}, tags=[]
        )
        assert f.sort_key == "support desk"

    def test_bundles_fall_back_to_spec_name_then_item_name(self):
        assert derive_facets("bundles", name="a", spec={"name": "Bee"}, tags=[]).sort_key == "bee"
        assert derive_facets("bundles", name="Cee", spec={}, tags=[]).sort_key == "cee"

    def test_skills_sort_by_their_displayed_title_not_the_raw_id(self):
        # Registry skill ids carry provenance ("--owner-repo--hash") that the UI
        # strips. Sorting on the raw id would order the list differently from
        # what the user reads on the cards.
        f = derive_facets("skills", name="action-creator--owner-repo--9f2a", spec={}, tags=[])
        assert f.sort_key == "action creator"

    def test_skills_strip_a_repo_suffix_glued_on_without_the_separator(self):
        f = derive_facets(
            "skills",
            name="frontend-design-anthropics-claude-code",
            spec={},
            tags=["repo:anthropics/claude-code"],
        )
        assert f.sort_key == "frontend design"

    def test_skills_prefer_an_explicit_display_name(self):
        f = derive_facets("skills", name="pdf-fill--x--1", spec={"display_name": "PDF Filler"}, tags=[])
        assert f.sort_key == "pdf filler"

    def test_falls_back_to_the_raw_name_when_prettifying_empties_it(self):
        f = derive_facets("skills", name="--owner-repo--9f2a", spec={}, tags=[])
        assert f.sort_key == "--owner-repo--9f2a"


class TestFeatured:
    def test_featured_tag_sets_the_flag(self):
        assert derive_facets("skills", name="x", spec={}, tags=["featured"]).featured is True

    def test_absent_featured_tag_is_false(self):
        assert derive_facets("skills", name="x", spec={}, tags=["category:other"]).featured is False


class TestTolerance:
    def test_survives_null_spec_and_tags(self):
        f = derive_facets("skills", name="x", spec=None, tags=None)
        assert (f.category, f.sort_key, f.featured) == (None, "x", False)

    def test_survives_non_mapping_nested_spec(self):
        # Sources are external; raw_spec/metadata are whatever the upstream
        # served. A string where a mapping was expected must not raise.
        f = derive_facets("mcp_servers", name="x", spec={"raw_spec": "nope"}, tags=[])
        assert f.category is None

    def test_survives_non_string_tags(self):
        f = derive_facets("skills", name="x", spec={}, tags=["category:ok", 5, None])
        assert f.category == "ok"


class TestApplyFacets:
    """`apply_facets` refreshes an already-loaded item after a re-sync.

    A source can retag or rename an entry between syncs; the update path
    overwrites name/spec/tags, so the derived columns have to follow or the
    catalog keeps sorting and faceting by what the item used to be.
    """

    class _Item:
        def __init__(self, name, spec, tags):
            self.name, self.spec, self.tags = name, spec, tags
            self.category = "stale"
            self.sort_key = "stale"
            self.featured = True

    def test_rewrites_all_three_columns_from_current_content(self):
        from agentarea_registry.application.catalog_facets import apply_facets

        item = self._Item("csv-clean--acme--1", {}, ["category:data"])
        apply_facets(item, "skills")
        assert (item.category, item.sort_key, item.featured) == ("data", "csv clean", False)

    def test_clears_a_category_the_source_dropped(self):
        from agentarea_registry.application.catalog_facets import apply_facets

        item = self._Item("x", {}, [])
        apply_facets(item, "skills")
        assert item.category is None

    def test_returns_the_item_for_chaining(self):
        from agentarea_registry.application.catalog_facets import apply_facets

        item = self._Item("x", {}, [])
        assert apply_facets(item, "skills") is item
