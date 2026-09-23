"use client";

import { useEffect, useRef, useState } from "react";

import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import type { CustomOAuthAppCredentials } from "@/lib/oauth-app";
import type { SecretResponse } from "@/api/client";

const MANUAL = "manual";

/**
 * Collect a client ID and secret, each either typed in or picked from a
 * workspace secret.
 *
 * Shared by the catalog's one-click connect flow and the MCP connection page —
 * both talk to the same API resolver, so they must offer the same two sources
 * and the same "exactly one of them" rule.
 */
export function CustomOAuthAppFields({
  loadSecrets,
  onChange,
  disabled,
}: {
  loadSecrets: () => Promise<SecretResponse[]>;
  onChange: (credentials: CustomOAuthAppCredentials) => void;
  disabled?: boolean;
}) {
  const [clientId, setClientId] = useState("");
  const [clientSecret, setClientSecret] = useState("");
  const [clientIdSource, setClientIdSource] = useState(MANUAL);
  const [clientSecretSource, setClientSecretSource] = useState(MANUAL);
  const [secrets, setSecrets] = useState<SecretResponse[] | null>(null);
  const [secretsError, setSecretsError] = useState<string | null>(null);
  const reusableSecrets = (secrets ?? []).filter((secret) => !secret.owner);

  const onChangeRef = useRef(onChange);
  onChangeRef.current = onChange;

  useEffect(() => {
    let active = true;
    loadSecrets()
      .then((loaded) => {
        if (active) setSecrets(loaded);
      })
      .catch((error: unknown) => {
        if (!active) return;
        setSecretsError(
          error instanceof Error
            ? error.message
            : "Failed to load workspace secrets"
        );
        setSecrets([]);
      });
    return () => {
      active = false;
    };
  }, [loadSecrets]);

  useEffect(() => {
    onChangeRef.current({
      client_id: clientIdSource === MANUAL ? clientId.trim() : undefined,
      client_secret: clientSecretSource === MANUAL ? clientSecret : undefined,
      client_id_secret_id:
        clientIdSource === MANUAL ? undefined : clientIdSource,
      client_secret_secret_id:
        clientSecretSource === MANUAL ? undefined : clientSecretSource,
    });
  }, [clientId, clientSecret, clientIdSource, clientSecretSource]);

  return (
    <div className="space-y-3">
      <div className="grid gap-3 sm:grid-cols-2">
        <div className="space-y-2">
          <Select
            value={clientIdSource}
            onValueChange={setClientIdSource}
            disabled={disabled}
          >
            <SelectTrigger aria-label="OAuth client ID source">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value={MANUAL}>Enter client ID</SelectItem>
              {reusableSecrets.map((secret) => (
                <SelectItem key={secret.id} value={secret.id}>
                  {secret.name}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          {clientIdSource === MANUAL && (
            <Input
              value={clientId}
              onChange={(event) => setClientId(event.target.value)}
              aria-label="OAuth client ID"
              placeholder="Client ID"
              autoComplete="off"
              disabled={disabled}
            />
          )}
        </div>
        <div className="space-y-2">
          <Select
            value={clientSecretSource}
            onValueChange={setClientSecretSource}
            disabled={disabled}
          >
            <SelectTrigger aria-label="OAuth client secret source">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value={MANUAL}>Enter client secret</SelectItem>
              {reusableSecrets.map((secret) => (
                <SelectItem key={secret.id} value={secret.id}>
                  {secret.name}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          {clientSecretSource === MANUAL && (
            <Input
              value={clientSecret}
              onChange={(event) => setClientSecret(event.target.value)}
              aria-label="OAuth client secret"
              placeholder="Client secret"
              type="password"
              autoComplete="new-password"
              disabled={disabled}
            />
          )}
        </div>
      </div>
      {secretsError && <p className="text-xs text-red-600">{secretsError}</p>}
      {secrets !== null && reusableSecrets.length === 0 && (
        <p className="text-xs text-muted-foreground">
          No reusable workspace secrets yet. You can enter both values here.
        </p>
      )}
    </div>
  );
}
