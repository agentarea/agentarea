/**
 * The API a command talks to, and the host a stored sign-in belongs to.
 *
 * A stored token is bound to the origin (scheme + host + port) it was issued
 * for, so pointing the CLI at another host — by flag, env var or saved config —
 * never hands it a bearer token minted for somewhere else.
 */

export const DEFAULT_API_URL = 'http://localhost:8000';

export function normalizeApiUrl(url: string): string {
	return url.trim().replace(/\/+$/, '');
}

/**
 * `scheme://host[:port]` of *url*, lower-cased with the default port dropped,
 * or null when it is not an http(s) URL.
 */
export function apiOrigin(url: string | undefined): string | null {
	if (!url) {
		return null;
	}

	let parsed: URL;
	try {
		parsed = new URL(url.trim());
	} catch {
		return null;
	}

	if (parsed.protocol !== 'http:' && parsed.protocol !== 'https:') {
		return null;
	}

	return parsed.origin;
}

/**
 * Whether a token issued for *issuedFor* may be sent to *target*. A token with
 * no recorded host is never sent: nothing proves it belongs to *target*.
 */
export function isSameApiOrigin(
	issuedFor: string | undefined,
	target: string,
): boolean {
	const issued = apiOrigin(issuedFor);
	return issued !== null && issued === apiOrigin(target);
}
