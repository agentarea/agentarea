-- The browse filter (_browse_filter) is shared by the page, its total and
-- the facets; an empty string is no filter on that dimension.

-- name: BrowseRecommended :many
SELECT * FROM registry_items WHERE registry_type = @registry_type AND registry_active
  AND (registry_workspace_id IS NULL OR registry_workspace_id = @workspace_id::text)
  AND (@category::text = '' OR category = @category::text)
  AND (@protocol::text = '' OR protocol = @protocol::text)
  AND (@hosting::text = '' OR hosting = @hosting::text)
  AND (@pricing::text = '' OR pricing = @pricing::text)
  AND (@pattern::text = '' OR name ILIKE @pattern::text OR description ILIKE @pattern::text)
ORDER BY featured DESC, registry_priority, recommendation_rank, sort_key, id
LIMIT @lim OFFSET @off;

-- name: BrowseByName :many
SELECT * FROM registry_items WHERE registry_type = @registry_type AND registry_active
  AND (registry_workspace_id IS NULL OR registry_workspace_id = @workspace_id::text)
  AND (@category::text = '' OR category = @category::text)
  AND (@protocol::text = '' OR protocol = @protocol::text)
  AND (@hosting::text = '' OR hosting = @hosting::text)
  AND (@pricing::text = '' OR pricing = @pricing::text)
  AND (@pattern::text = '' OR name ILIKE @pattern::text OR description ILIKE @pattern::text)
ORDER BY sort_key, id
LIMIT @lim OFFSET @off;

-- name: BrowseTotal :one
SELECT count(*) FROM registry_items WHERE registry_type = @registry_type AND registry_active
  AND (registry_workspace_id IS NULL OR registry_workspace_id = @workspace_id::text)
  AND (@category::text = '' OR category = @category::text)
  AND (@protocol::text = '' OR protocol = @protocol::text)
  AND (@hosting::text = '' OR hosting = @hosting::text)
  AND (@pricing::text = '' OR pricing = @pricing::text)
  AND (@pattern::text = '' OR name ILIKE @pattern::text OR description ILIKE @pattern::text);

-- name: CategoryCounts :many
SELECT category::text AS value, count(*) AS n FROM registry_items WHERE registry_type = @registry_type AND registry_active
  AND (registry_workspace_id IS NULL OR registry_workspace_id = @workspace_id::text)
  AND (@category::text = '' OR category = @category::text)
  AND (@protocol::text = '' OR protocol = @protocol::text)
  AND (@hosting::text = '' OR hosting = @hosting::text)
  AND (@pricing::text = '' OR pricing = @pricing::text)
  AND (@pattern::text = '' OR name ILIKE @pattern::text OR description ILIKE @pattern::text) AND category IS NOT NULL
GROUP BY category
ORDER BY CASE WHEN lower(category) = 'other' THEN 1 ELSE 0 END, category;

-- name: ProtocolCounts :many
SELECT protocol AS value, count(*) AS n FROM registry_items WHERE registry_type = @registry_type AND registry_active
  AND (registry_workspace_id IS NULL OR registry_workspace_id = @workspace_id::text)
  AND (@category::text = '' OR category = @category::text)
  AND (@protocol::text = '' OR protocol = @protocol::text)
  AND (@hosting::text = '' OR hosting = @hosting::text)
  AND (@pricing::text = '' OR pricing = @pricing::text)
  AND (@pattern::text = '' OR name ILIKE @pattern::text OR description ILIKE @pattern::text) GROUP BY protocol;

-- name: HostingCounts :many
SELECT hosting AS value, count(*) AS n FROM registry_items WHERE registry_type = @registry_type AND registry_active
  AND (registry_workspace_id IS NULL OR registry_workspace_id = @workspace_id::text)
  AND (@category::text = '' OR category = @category::text)
  AND (@protocol::text = '' OR protocol = @protocol::text)
  AND (@hosting::text = '' OR hosting = @hosting::text)
  AND (@pricing::text = '' OR pricing = @pricing::text)
  AND (@pattern::text = '' OR name ILIKE @pattern::text OR description ILIKE @pattern::text) GROUP BY hosting;

-- name: PricingCounts :many
SELECT pricing AS value, count(*) AS n FROM registry_items WHERE registry_type = @registry_type AND registry_active
  AND (registry_workspace_id IS NULL OR registry_workspace_id = @workspace_id::text)
  AND (@category::text = '' OR category = @category::text)
  AND (@protocol::text = '' OR protocol = @protocol::text)
  AND (@hosting::text = '' OR hosting = @hosting::text)
  AND (@pricing::text = '' OR pricing = @pricing::text)
  AND (@pattern::text = '' OR name ILIKE @pattern::text OR description ILIKE @pattern::text) GROUP BY pricing;
