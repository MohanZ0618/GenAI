import { beforeEach, vi } from "vitest";

beforeEach(() => {
  vi.stubGlobal(
    "fetch",
    vi
      .fn()
      .mockRejectedValue(
        new Error(
          "External network is disabled in tests; provide a fetch mock.",
        ),
      ),
  );
});
