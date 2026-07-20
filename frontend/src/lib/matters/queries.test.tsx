import type { ReactNode } from "react";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { useMatters } from "./queries";
import type { Matter } from "./types";

const MATTER: Matter = {
  id: "m1",
  firm_id: "f1",
  matter_type: "immigration",
  title: "Test matter",
  client_ref: null,
  status: "open",
  created_by: "u1",
  created_at: "2026-07-01T00:00:00Z",
};

function mockFetchOnce(body: unknown, status = 200) {
  const fetchMock = vi.fn().mockResolvedValue({
    status,
    json: async () => body,
  } as Response);
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

function wrapper({ children }: { children: ReactNode }) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("useMatters", () => {
  it("unwraps the {success, data} envelope into the matter list", async () => {
    mockFetchOnce({ success: true, data: { matters: [MATTER] }, error: null });

    const { result } = renderHook(() => useMatters(), { wrapper });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data?.matters).toHaveLength(1);
    expect(result.current.data?.matters[0].title).toBe("Test matter");
  });

  it("surfaces the envelope error message on a failed envelope", async () => {
    mockFetchOnce({ success: false, data: null, error: "matter store unavailable" });

    const { result } = renderHook(() => useMatters(), { wrapper });

    await waitFor(() => expect(result.current.isError).toBe(true));
    expect(result.current.error).toMatchObject({ message: "matter store unavailable" });
  });
});
