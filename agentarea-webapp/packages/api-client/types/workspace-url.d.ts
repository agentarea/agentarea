export declare class MissingWorkspaceError extends Error {
    readonly path: string;
    constructor(path: string);
}
export declare class InvalidWorkspaceError extends Error {
    readonly slug: string;
    constructor(slug: string);
}
/** True when `url` still carries the workspace placeholder in its path. */
export declare function isWorkspaceScoped(url: string): boolean;
/**
 * Put `slug` into the workspace placeholder of `url`. A URL without one is
 * returned untouched; a URL with one throws on a missing or malformed slug.
 */
export declare function fillWorkspace(url: string, slug: string | null | undefined): string;
