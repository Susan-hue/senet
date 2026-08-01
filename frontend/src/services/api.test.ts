import { afterEach, describe, expect, it, vi } from "vitest";
import { ApiError, apiRequest } from "./api";

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("apiRequest", () => {
  it("reports a genuine transport failure as a network ApiError", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("Failed to fetch")));

    await expect(apiRequest("/api/v1/anything/")).rejects.toMatchObject({
      name: "ApiError",
      status: 0,
    });
  });

  it("re-throws an abort so a cancelled request is not reported as an outage", async () => {
    const abort = new DOMException("The operation was aborted.", "AbortError");
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(abort));

    const error = await apiRequest("/api/v1/anything/").catch((err: unknown) => err);
    expect(error).toBe(abort);
    expect(error).not.toBeInstanceOf(ApiError);
  });

  it("surfaces the server's message and field errors on an error envelope", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: false,
        status: 400,
        json: async () => ({
          status: "error",
          data: null,
          message: "Could not save the score.",
          errors: { exam_score: ["Enter a number."] },
        }),
      }),
    );

    await expect(apiRequest("/api/v1/anything/")).rejects.toMatchObject({
      message: "Could not save the score.",
      status: 400,
      fieldErrors: { exam_score: ["Enter a number."] },
    });
  });
});
