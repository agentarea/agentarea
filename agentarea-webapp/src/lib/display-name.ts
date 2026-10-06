/** The name traits of a Kratos identity, as the identity schema stores them. */
export interface NameTraits {
  name?: { first?: string; last?: string };
  username?: string;
  email?: string;
}

/** How a person is called across the app: full name, else username, else email. */
export function displayName(
  traits: NameTraits | undefined
): string | undefined {
  const fullName = [traits?.name?.first, traits?.name?.last]
    .filter(Boolean)
    .join(" ");
  return fullName || traits?.username || traits?.email;
}
