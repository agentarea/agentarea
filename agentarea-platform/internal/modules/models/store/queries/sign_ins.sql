-- name: PutSignIn :exec
INSERT INTO provider_config_sign_ins (provider_config_id, user_id, workspace_id, device_auth_id, user_code, expires_at)
VALUES (@provider_config_id, @user_id, @workspace_id, @device_auth_id, @user_code, @expires_at)
ON CONFLICT (provider_config_id, user_id) DO UPDATE
SET device_auth_id = EXCLUDED.device_auth_id, user_code = EXCLUDED.user_code, expires_at = EXCLUDED.expires_at;

-- name: GetSignIn :one
SELECT device_auth_id, user_code, expires_at FROM provider_config_sign_ins
WHERE provider_config_id = @provider_config_id AND user_id = @user_id AND workspace_id = @workspace_id;

-- name: DeleteSignIn :exec
DELETE FROM provider_config_sign_ins
WHERE provider_config_id = @provider_config_id AND user_id = @user_id AND workspace_id = @workspace_id;
