import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { RunStatusChip, runStatusChip, severityTone } from "./Chip";

describe("runStatusChip", () => {
  it("maps every run status to a stable tone and label", () => {
    expect(runStatusChip("queued")).toEqual({ tone: "neutral", label: "Queued" });
    expect(runStatusChip("running")).toEqual({ tone: "info", label: "Running" });
    expect(runStatusChip("awaiting_input")).toEqual({
      tone: "warn",
      label: "Awaiting input",
    });
    expect(runStatusChip("done")).toEqual({ tone: "good", label: "Done" });
    expect(runStatusChip("error")).toEqual({ tone: "danger", label: "Error" });
  });
});

describe("severityTone", () => {
  it("maps finding severities to tones", () => {
    expect(severityTone("critical")).toBe("danger");
    expect(severityTone("warning")).toBe("warn");
    expect(severityTone("info")).toBe("info");
  });
});

describe("RunStatusChip", () => {
  it("renders the mapped label", () => {
    render(<RunStatusChip status="awaiting_input" />);
    expect(screen.getByText("Awaiting input")).toBeInTheDocument();
  });
});
