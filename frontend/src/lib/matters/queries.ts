/**
 * TanStack Query hooks for the matter workspace. Query keys live in one place
 * so invalidation is consistent. Cross-component/route state (e.g. carrying a
 * package run's parked review payload from the start response to the run view)
 * is held in the Query cache via setQueryData rather than a separate store —
 * see the Zustand-skip note in queries. No SSE in v1: matter runs are
 * non-streaming, so polling covers liveness.
 */
"use client";

import {
  useMutation,
  useQuery,
  useQueryClient,
  type UseQueryResult,
} from "@tanstack/react-query";

import {
  createMatter,
  getInbox,
  getMatter,
  getPackageRun,
  getRun,
  listMatters,
  listPackages,
  resumeRun,
  startMatterRun,
  uploadMatterDocuments,
} from "./api";
import type {
  InboxData,
  Matter,
  MatterDetailData,
  MatterListData,
  PackageListData,
  PackageRunStatusData,
  RunStatusData,
} from "./types";

/** Poll cadence for a live (queued/running) run, in milliseconds. */
const RUN_POLL_MS = 2000;

export const matterKeys = {
  all: ["matters"] as const,
  list: () => [...matterKeys.all, "list"] as const,
  detail: (id: string) => [...matterKeys.all, "detail", id] as const,
};

export const runKeys = {
  all: ["runs"] as const,
  detail: (id: string) => [...runKeys.all, "detail", id] as const,
};

export const inboxKeys = {
  all: ["inbox"] as const,
};

export const packageKeys = {
  all: ["packages"] as const,
};

export const packageRunKeys = {
  status: (packageId: string, runId: string) =>
    ["packageRun", "status", packageId, runId] as const,
  /**
   * The parked-review payload carried from a package run's start response to
   * the run view. Held in the Query cache (setQueryData) rather than a store —
   * this is the only cross-route state, and Query covers it, so Zustand is not
   * used in v1. On a hard reload this cache is empty; see the run view.
   */
  startPayload: (runId: string) => ["packageRun", "startPayload", runId] as const,
};

export function useMatters(): UseQueryResult<MatterListData> {
  return useQuery({
    queryKey: matterKeys.list(),
    queryFn: listMatters,
  });
}

export function useMatter(matterId: string): UseQueryResult<MatterDetailData> {
  return useQuery({
    queryKey: matterKeys.detail(matterId),
    queryFn: () => getMatter(matterId),
    enabled: matterId.length > 0,
  });
}

/**
 * A matter-path run's status. Polls while the run is queued/running; stops once
 * it parks (awaiting_input), finishes (done), or errors — those states change
 * only in response to a user action, not on their own.
 */
export function useRun(runId: string): UseQueryResult<RunStatusData> {
  return useQuery({
    queryKey: runKeys.detail(runId),
    queryFn: () => getRun(runId),
    enabled: runId.length > 0,
    refetchInterval: (query) => {
      const status = query.state.data?.run.status;
      return status === "queued" || status === "running" ? RUN_POLL_MS : false;
    },
  });
}

/**
 * A package-endpoint run's status (autofill/preflight). Polls while it is still
 * awaiting review is unnecessary — these runs change state only on resume — so
 * no interval; the run view invalidates after a resume.
 */
export function usePackageRun(
  packageId: string,
  runId: string,
): UseQueryResult<PackageRunStatusData> {
  return useQuery({
    queryKey: packageRunKeys.status(packageId, runId),
    queryFn: () => getPackageRun(packageId, runId),
    enabled: packageId.length > 0 && runId.length > 0,
  });
}

export function useInbox(): UseQueryResult<InboxData> {
  return useQuery({
    queryKey: inboxKeys.all,
    queryFn: getInbox,
  });
}

export function usePackages(): UseQueryResult<PackageListData> {
  return useQuery({
    queryKey: packageKeys.all,
    queryFn: listPackages,
    staleTime: 5 * 60 * 1000, // manifests are static within a process
  });
}

// --- Mutations --------------------------------------------------------------

export function useCreateMatter() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (input: { matter_type: string; title: string; client_ref?: string | null }) =>
      createMatter(input),
    onSuccess: (matter: Matter) => {
      queryClient.invalidateQueries({ queryKey: matterKeys.list() });
      return matter;
    },
  });
}

export function useUploadDocuments(matterId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (files: File[]) => uploadMatterDocuments(matterId, files),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: matterKeys.detail(matterId) });
    },
  });
}

export function useStartMatterRun(matterId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (input: { packageId: string; initial?: Record<string, unknown> }) =>
      startMatterRun(matterId, input.packageId, input.initial ?? {}),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: matterKeys.detail(matterId) });
    },
  });
}

export function useResumeRun(runId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (payload: Record<string, unknown>) => resumeRun(runId, payload),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: runKeys.detail(runId) });
      queryClient.invalidateQueries({ queryKey: inboxKeys.all });
    },
  });
}
