import { describe, expect, it } from "vitest";
import { zEgressExitCreate } from "@/api/client/zod.gen";
import {
  emptyEgressExitForm,
  sendsPlaintextCredentials,
  toEgressExitCreate,
  toEgressExitUpdate,
} from "./egress-exit-form";

const SECRET_ID = "8a6e0804-2bd0-4672-b79e-d97ae1e4128b";

describe("egress exit form", () => {
  it("sends blanks as null and a valid body", () => {
    const body = toEgressExitCreate({
      ...emptyEgressExitForm(),
      name: " office ",
      upstream_url: " https://proxy.example.com:8443 ",
      username: "  ",
    });
    expect(body).toEqual({
      name: "office",
      description: null,
      upstream_url: "https://proxy.example.com:8443",
      username: null,
      password_secret_id: null,
      allow_plaintext_credentials: false,
    });
    expect(zEgressExitCreate.safeParse(body).success).toBe(true);
  });

  it("clears a removed password on update rather than leaving it unchanged", () => {
    const body = toEgressExitUpdate({
      ...emptyEgressExitForm(),
      name: "office",
      upstream_url: "https://proxy.example.com:8443",
      username: "bot",
      password_secret_id: "",
    });
    expect(body).toHaveProperty("password_secret_id", null);
  });

  it("asks for plaintext consent only for a sign-in to a non-https proxy", () => {
    const form = {
      ...emptyEgressExitForm(),
      upstream_url: "socks5://proxy.example.com:1080",
      username: "bot",
      password_secret_id: SECRET_ID,
      allow_plaintext_credentials: true,
    };
    expect(sendsPlaintextCredentials(form)).toBe(true);
    expect(toEgressExitCreate(form).allow_plaintext_credentials).toBe(true);

    const https = { ...form, upstream_url: "https://proxy.example.com:8443" };
    expect(sendsPlaintextCredentials(https)).toBe(false);
    // A consent left on from an earlier http address is not sent along.
    expect(toEgressExitCreate(https).allow_plaintext_credentials).toBe(false);

    expect(sendsPlaintextCredentials({ ...form, username: "" })).toBe(false);
  });
});
