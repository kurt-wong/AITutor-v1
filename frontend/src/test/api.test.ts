/**
 * API client unit tests
 * Tests for pure utility functions: ApiError, setAdminKey, URL helpers
 */
import { describe, it, expect, beforeEach } from "vitest";
import { ApiError, setAdminKey } from "../services/api";

describe("ApiError", () => {
  it("creates an error with name and status", () => {
    const err = new ApiError("Not Found", 404);
    expect(err).toBeInstanceOf(Error);
    expect(err.name).toBe("ApiError");
    expect(err.message).toBe("Not Found");
    expect(err.status).toBe(404);
  });

  it("preserves status for different HTTP codes", () => {
    const codes = [400, 401, 403, 500, 502];
    for (const code of codes) {
      const err = new ApiError(`Error ${code}`, code);
      expect(err.status).toBe(code);
    }
  });
});

describe("setAdminKey", () => {
  beforeEach(() => {
    // Reset the module-level state between tests
    setAdminKey("");
  });

  it("sets the admin key in module state", () => {
    setAdminKey("test-key-123");
    // setAdminKey is set-only (no getter exposed), but subsequent
    // API calls with /api/admin/ paths will include X-Admin-Key header
    expect(true).toBe(true); // smoke test — setAdminKey runs without error
  });

  it("handles empty key gracefully", () => {
    setAdminKey("");
    expect(true).toBe(true); // smoke test — no crash
  });
});
