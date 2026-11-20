// These tests exercise the retry boundary, not Keitaro's distribution algorithm
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { api, ApiError, intentKey } from "./api";

beforeEach(() => {
  const storage = new Map<string, string>();
  vi.stubGlobal("sessionStorage", {
    getItem: (key: string) => storage.get(key) ?? null,
    setItem: (key: string, value: string) => storage.set(key, value),
  });
});
afterEach(() => vi.unstubAllGlobals());

describe("submission intent", () => {
  it("reuses the submission key after a retry, but separates changed input", () => {
    const first = intentKey("create", { name: "AU" });
    expect(intentKey("create", { name: "AU" })).toBe(first);
    expect(intentKey("create", { name: "DE" })).not.toBe(first);
  });
  it("keeps independent stream publications separate", () => {
    expect(intentKey("stream:1", { version: 2 })).not.toBe(
      intentKey("stream:2", { version: 2 }),
    );
  });
});

describe("API boundary", () => {
  it("sends an app token and idempotency key without embedding a Keitaro key", async () => {
    sessionStorage.setItem("app-token", "wrapper-token");
    const fetch = vi
      .fn()
      .mockResolvedValue(
        new Response('{"status":"completed"}', { status: 200 }),
      );
    vi.stubGlobal("fetch", fetch);
    expect(
      await api("/campaigns", "POST", { name: "AU" }, "submission"),
    ).toEqual({ status: "completed" });
    expect(fetch.mock.calls[0][1].headers).toEqual({
      "Content-Type": "application/json",
      "X-App-Token": "wrapper-token",
      "Idempotency-Key": "submission",
    });
  });
  it("preserves the server error and correlation ID", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(
          JSON.stringify({
            error: {
              code: "external_conflict",
              message: "Keitaro changed",
              request_id: "request123",
            },
          }),
          { status: 409 },
        ),
      ),
    );
    try {
      await api("/streams/1/publish");
      expect.fail("Expected conflict");
    } catch (error) {
      expect(error).toBeInstanceOf(ApiError);
      expect(error).toMatchObject({
        code: "external_conflict",
        requestId: "request123",
      });
    }
  });
  it("treats an unreadable response as unknown to the browser", async () => {
    vi.stubGlobal(
      "fetch",
      vi
        .fn()
        .mockResolvedValue(new Response("<html>proxy</html>", { status: 502 })),
    );
    await expect(api("/campaigns")).rejects.toMatchObject({
      code: "invalid_response",
    });
  });
});
