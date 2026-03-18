import { listAPIKeys } from "@/lib/api";
import APIKeysClient from "./APIKeysClient";

const APIKeyStatus = {
  ACTIVE: "active",
  REVOKED: "revoked",
  EXPIRED: "expired",
} as const;

function deriveStatus(key: any): (typeof APIKeyStatus)[keyof typeof APIKeyStatus] {
  if (!key.is_active) return APIKeyStatus.REVOKED;
  if (key.expires_at && new Date(key.expires_at) < new Date()) return APIKeyStatus.EXPIRED;
  return APIKeyStatus.ACTIVE;
}

export default async function APIKeysContent() {
  const { data, error } = await listAPIKeys();

  const keys = error
    ? []
    : ((data as any[]) || []).map((key) => ({
        ...key,
        status: deriveStatus(key),
      }));

  return <APIKeysClient initialKeys={keys} />;
}
