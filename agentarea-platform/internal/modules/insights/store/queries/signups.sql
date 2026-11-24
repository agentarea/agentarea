-- name: InsertSignupAttribution :one
INSERT INTO signup_attributions (identity_id, created_at, updated_at, method, channel, referrer_host, landing_host,
  landing_path, utm_source, utm_medium, utm_campaign)
VALUES (@identity_id, @created_at, @updated_at, sqlc.narg('method'), @channel, sqlc.narg('referrer_host'),
  sqlc.narg('landing_host'), sqlc.narg('landing_path'), sqlc.narg('utm_source'), sqlc.narg('utm_medium'), sqlc.narg('utm_campaign'))
ON CONFLICT (identity_id) DO NOTHING
RETURNING identity_id;
