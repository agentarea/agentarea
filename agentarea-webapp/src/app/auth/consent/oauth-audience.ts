export function grantedAccessTokenAudience(
  requestedAudience: string[] | undefined,
  clientAudience: string[] | undefined
): string[] {
  return requestedAudience && requestedAudience.length > 0
    ? requestedAudience
    : clientAudience || [];
}
