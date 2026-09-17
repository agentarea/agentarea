import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { beforeEach, describe, expect, it, vi } from "vitest";
import AuthGuard from "./AuthGuard";

const auth = vi.hoisted(() => ({ isLoaded: false, isSignedIn: false }));

vi.mock("@/hooks/useAuth", () => ({ useAuth: () => auth }));
vi.mock("next/navigation", () => ({ useRouter: () => ({ push: vi.fn() }) }));
vi.mock("@/components/LoadingSpinner", () => ({
  LoadingSpinner: () => <div>Loading session</div>,
}));

describe("AuthGuard", () => {
  beforeEach(() => {
    auth.isLoaded = false;
    auth.isSignedIn = false;
  });

  function renderGuard() {
    return renderToStaticMarkup(
      <AuthGuard>
        <div>Private settings</div>
      </AuthGuard>
    );
  }

  it("hides protected content while the initial session loads", () => {
    const html = renderGuard();
    expect(html).toContain("Loading session");
    expect(html).not.toContain("Private settings");
  });

  it("keeps authenticated content mounted during a session refresh", () => {
    auth.isSignedIn = true;
    expect(renderGuard()).toContain("Private settings");
  });

  it("hides protected content when a refreshed session is unauthenticated", () => {
    auth.isLoaded = true;
    expect(renderGuard()).not.toContain("Private settings");
  });
});
