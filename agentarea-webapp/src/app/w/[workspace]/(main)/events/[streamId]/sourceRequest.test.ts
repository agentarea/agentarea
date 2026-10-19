import { describe, expect, it } from "vitest";
import type { SourceType } from "@/lib/sourceTypes";
import {
  missingSourceFields,
  sourceKinds,
  toSourceRequest,
  type SourceFormValues,
} from "./sourceRequest";

function entry(overrides: Partial<SourceType>): SourceType {
  return {
    slug: "payments",
    name: "Payments",
    description: "",
    icon: "webhook",
    icon_url: null,
    delivery: "webhook",
    credentials: [],
    config: [],
    events: [],
    event: {
      kind: "{body:event}",
      key: "{body:id}",
      session_key: null,
      sender: null,
      occurred_at: null,
    },
    verification_scheme: "api_lookup",
    verification_header: null,
    continues_sessions: false,
    replies: false,
    ...overrides,
  };
}

const payments = entry({
  credentials: [
    {
      key: "secret_key",
      label: "Secret Key",
      placeholder: "",
      required: true,
      issued: false,
    },
  ],
  config: [
    {
      key: "shop_id",
      label: "Shop ID",
      placeholder: "",
      required: true,
      issued: false,
    },
  ],
});

const generic = entry({
  slug: "generic_webhook",
  name: "Webhook",
  event: {
    kind: "webhook",
    key: "{header:webhook-id}",
    session_key: null,
    sender: null,
    occurred_at: null,
  },
  credentials: [
    {
      key: "signing_secret",
      label: "Signing Secret",
      placeholder: "",
      required: true,
      issued: true,
    },
  ],
});

const chat = entry({ slug: "chat_bot", delivery: "both" });

const blank: SourceFormValues = { secrets: {}, settings: {}, templates: {} };

describe("toSourceRequest", () => {
  it("sends a picked secret by reference and a setting trimmed", () => {
    expect(
      toSourceRequest(payments, {
        ...blank,
        secrets: { secret_key: "s-1" },
        settings: { shop_id: " 506751 " },
      })
    ).toEqual({
      source_type: "payments",
      kind: "webhook",
      credentials: { secret_key: { secret_id: "s-1" } },
      config: { shop_id: "506751" },
    });
  });

  it("leaves out what was left blank, so an issued secret is generated", () => {
    expect(
      toSourceRequest(generic, { ...blank, secrets: { signing_secret: "" } })
    ).toEqual({
      source_type: "generic_webhook",
      kind: "webhook",
      credentials: {},
      config: {},
    });
  });

  it("drops values kept from a type picked before", () => {
    expect(
      toSourceRequest(generic, {
        ...blank,
        secrets: { secret_key: "s-1" },
        settings: { shop_id: "1" },
        templates: {},
      })
    ).toEqual({
      source_type: "generic_webhook",
      kind: "webhook",
      credentials: {},
      config: {},
    });
  });

  it("sends the generic webhook's own event templates, trimmed, and only those set", () => {
    expect(
      toSourceRequest(generic, {
        ...blank,
        templates: {
          kind: " {body:trigger.name}.{body:event.op} ",
          key: "{body:id}",
          session_key: "",
        },
      }).event_templates
    ).toEqual({
      kind: "{body:trigger.name}.{body:event.op}",
      key: "{body:id}",
    });
  });

  it("never sends event templates for a type the catalog describes", () => {
    expect(
      toSourceRequest(payments, { ...blank, templates: { key: "{body:x}" } })
    ).not.toHaveProperty("event_templates");
  });

  it("uses the chosen way in for a type that can do both, and the only one otherwise", () => {
    expect(sourceKinds(chat)).toEqual(["webhook", "poll"]);
    expect(toSourceRequest(chat, { ...blank, kind: "poll" }).kind).toBe("poll");
    expect(toSourceRequest(chat, blank).kind).toBe("webhook");
    expect(toSourceRequest(payments, { ...blank, kind: "poll" }).kind).toBe(
      "webhook"
    );
  });
});

describe("missingSourceFields", () => {
  it("names each required field left blank", () => {
    expect(
      missingSourceFields(payments, { ...blank, settings: { shop_id: " " } })
    ).toEqual(["secret_key", "shop_id"]);
  });

  it("asks nothing of a field the platform issues", () => {
    expect(missingSourceFields(generic, blank)).toEqual([]);
  });
});
