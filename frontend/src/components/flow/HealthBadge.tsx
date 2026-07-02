"use client";

import { useEffect, useState } from "react";

import { fetchHealth } from "@/lib/api";
import type { HealthInfo } from "@/lib/types";

type Status = "checking" | "online" | "offline";

export function HealthBadge() {
  const [status, setStatus] = useState<Status>("checking");
  const [info, setInfo] = useState<HealthInfo | null>(null);

  useEffect(() => {
    let isCancelled = false;
    fetchHealth()
      .then((health) => {
        if (isCancelled) return;
        setInfo(health);
        setStatus("online");
      })
      .catch(() => {
        if (!isCancelled) setStatus("offline");
      });
    return () => {
      isCancelled = true;
    };
  }, []);

  const dotClass =
    status === "online" ? "bg-good" : status === "offline" ? "bg-danger" : "bg-line-strong";

  return (
    <span className="inline-flex items-center gap-2 text-xs text-ink-soft">
      <span aria-hidden className={`size-2 rounded-full ${dotClass}`} />
      {status === "checking" && "Checking backend…"}
      {status === "offline" && "Backend offline — start it before extracting"}
      {status === "online" && info && (
        <>
          Backend online · {info.model} · {info.storage} storage
          {!info.gemini_key_present && (
            <span className="font-medium text-warn"> · Gemini key missing</span>
          )}
        </>
      )}
    </span>
  );
}
