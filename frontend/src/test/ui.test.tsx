import { render, screen } from "@testing-library/react";
import { FolderPlus } from "lucide-react";
import { Ring } from "@/components/Ring";
import { EmptyState, ErrorState } from "@/components/ui/states";
import { severityTone, statusTone } from "@/components/ui/badge";
import { duration, timeAgo } from "@/lib/utils";

describe("ui primitives", () => {
  it("ring shows the rounded value or a dash", () => {
    const { rerender } = render(<Ring value={73.6} label="score" />);
    expect(screen.getByText("74")).toBeInTheDocument();
    rerender(<Ring value={null} />);
    expect(screen.getByText("—")).toBeInTheDocument();
  });

  it("empty and error states are accessible", () => {
    render(<EmptyState icon={FolderPlus} title="No projects yet" description="Add one" />);
    expect(screen.getByRole("heading", { name: "No projects yet" })).toBeInTheDocument();
    render(<ErrorState error={new Error("boom")} />);
    expect(screen.getByRole("alert")).toHaveTextContent("boom");
  });

  it("maps severities and statuses to tones", () => {
    expect(severityTone("critical")).toBe("fail");
    expect(statusTone("completed")).toBe("pass");
    expect(statusTone("weird")).toBe("neutral");
  });

  it("formats durations and relative times", () => {
    expect(duration("2026-01-01T00:00:00Z", "2026-01-01T00:01:05Z")).toBe("1m 5s");
    expect(timeAgo(null)).toBe("never");
  });
});
