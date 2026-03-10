// Type declarations for psl module
// psl provides its own types but they are not properly exported in the package.json exports field

declare module "psl" {
  export type ErrorResult<T extends keyof errorCodes> = {
    input: string;
    error: {
      code: T;
      message: errorCodes[T];
    };
  };

  export const enum errorCodes {
    DOMAIN_TOO_SHORT = "Domain name too short",
    DOMAIN_TOO_LONG = "Domain name too long. It should be no more than 255 chars.",
    LABEL_STARTS_WITH_DASH = "Domain name label can not start with a dash.",
    LABEL_ENDS_WITH_DASH = "Domain name label can not end with a dash.",
    LABEL_TOO_LONG = "Domain name label should be at most 63 chars long.",
    LABEL_TOO_SHORT = "Domain name label should be at least 1 character long.",
    LABEL_INVALID_CHARS = "Domain name label can only contain alphanumeric characters or dashes.",
  }

  export type ParsedDomain = {
    input: string;
    tld: string | null;
    sld: string | null;
    domain: string | null;
    subdomain: string | null;
    listed: boolean;
  };

  export function parse(input: string): ParsedDomain | ErrorResult<keyof errorCodes>;
}
