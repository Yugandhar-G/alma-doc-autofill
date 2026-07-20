import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { InterruptPanel } from "./InterruptPanel";

describe("InterruptPanel kind dispatch", () => {
  it("renders the extraction review sections for extraction_review", () => {
    const payload = {
      passport: {
        document_type_requested: "passport",
        document_type_detected: "passport",
        data: { surname: "SMITH", given_names: "JANE" },
        warnings: [],
        model_used: null,
        source_hash: null,
      },
      g28: null,
    };

    render(<InterruptPanel kind="extraction_review" payload={payload} />);

    // The reused review primitives render the passport field descriptors.
    expect(screen.getByText("Review extracted data")).toBeInTheDocument();
    expect(screen.getByText("Surname")).toBeInTheDocument();
    expect(screen.getByText("Passport number")).toBeInTheDocument();
    expect(screen.getByDisplayValue("SMITH")).toBeInTheDocument();
  });

  it("renders the findings table for preflight_review", () => {
    const payload = {
      report: {
        case_type: "g28_filing",
        findings: [
          {
            check_id: "identity_name_match",
            severity: "critical",
            message: "Passport surname does not match the G-28 beneficiary family name.",
            refs: [],
          },
        ],
        checks_run: ["identity_name_match"],
        docs_examined: 2,
        ok: false,
      },
    };

    render(<InterruptPanel kind="preflight_review" payload={payload} />);

    expect(screen.getByText("Review pre-flight findings")).toBeInTheDocument();
    expect(
      screen.getByText(
        "Passport surname does not match the G-28 beneficiary family name.",
      ),
    ).toBeInTheDocument();
    expect(screen.getByText("identity_name_match")).toBeInTheDocument();
    expect(screen.getByText("critical")).toBeInTheDocument();
  });

  it("links out to the screener for matrix_review", () => {
    render(<InterruptPanel kind="matrix_review" payload={{}} />);
    const link = screen.getByRole("link", { name: /open the screener review/i });
    expect(link).toHaveAttribute("href", "/screener");
  });

  it("falls back to an informational panel for an unknown kind", () => {
    render(<InterruptPanel kind="mystery_review" payload={{ foo: "bar" }} />);
    expect(screen.getByText("Human review required")).toBeInTheDocument();
  });
});
