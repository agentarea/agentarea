import { useTranslations } from "next-intl";

/** Human label for a secret's owner or consumer type; an unknown type shows as-is. */
export function useSecretTypeLabel() {
  const t = useTranslations("SecretsPage.types");
  return (type: string) => (t.has(type) ? t(type) : type);
}
