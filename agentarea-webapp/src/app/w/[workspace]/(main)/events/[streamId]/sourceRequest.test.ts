import { describe, expect, it } from "vitest";
import type { StreamSourceTypeResponse } from "@/api/client/types.gen";
import { missingSourceFields, toSourceRequest } from "./sourceRequest";

const yookassa: StreamSourceTypeResponse = {
  webhook_type: "yookassa",
  name: "YooKassa",
  description: "",
  icon: "webhook",
  icon_url: null,
  verification: "api_lookup",
  credentials: [{ key: "secret_key", label: "Secret Key", required: true }],
  config: [{ key: "shop_id", label: "Shop ID", required: true }],
};

const generic: StreamSourceTypeResponse = {
  webhook_type: "generic",
  name: "Webhook",
  description: "",
  icon: "webhook",
  icon_url: null,
  verification: "signature",
  credentials: [
    { key: "signing_secret", label: "Signing Secret", required: false },
  ],
  config: [
    { key: "signature_header", label: "Header", required: false },
    { key: "signature_prefix", label: "Prefix", required: false },
  ],
};

describe("toSourceRequest", () => {
  it("sends a picked secret by reference and a setting trimmed", () => {
    expect(
      toSourceRequest(yookassa, {
        secrets: { secret_key: "s-1" },
        settings: { shop_id: " 506751 " },
      })
    ).toEqual({
      webhook_type: "yookassa",
      credentials: { secret_key: { secret_id: "s-1" } },
      config: { shop_id: "506751" },
    });
  });

  it("leaves out what was left blank, so an optional secret is issued", () => {
    expect(
      toSourceRequest(generic, {
        secrets: { signing_secret: "" },
        settings: { signature_header: "X-Sig", signature_prefix: "  " },
      })
    ).toEqual({
      webhook_type: "generic",
      credentials: {},
      config: { signature_header: "X-Sig" },
    });
  });

  it("drops values kept from a type picked before", () => {
    expect(
      toSourceRequest(generic, {
        secrets: { secret_key: "s-1" },
        settings: { shop_id: "1" },
      })
    ).toEqual({ webhook_type: "generic", credentials: {}, config: {} });
  });
});

describe("missingSourceFields", () => {
  it("names each required field left blank", () => {
    expect(
      missingSourceFields(yookassa, {
        secrets: {},
        settings: { shop_id: " " },
      })
    ).toEqual(["secret_key", "shop_id"]);
  });

  it("asks nothing of a type whose fields are optional", () => {
    expect(missingSourceFields(generic, { secrets: {}, settings: {} })).toEqual(
      []
    );
  });
});
