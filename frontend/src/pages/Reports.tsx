import { useParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { Bug, Code2, Download, FileSpreadsheet, FileText, GitBranch, Loader2, Network, Presentation, Table2 } from "lucide-react";
import { api, fileUrl, type ExportKind } from "@/lib/api";
import { timeAgo } from "@/lib/utils";
import { PageHeader } from "@/components/PageHeader";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";

interface Item { kind: ExportKind; listed: string; title: string; description: string; icon: typeof FileText; needs: "results" | "bugs" | "testcases" | "requirements" }

const ITEMS: { group: string; items: Item[] }[] = [
  {
    group: "For the business",
    items: [
      { kind: "qa_report_pdf", listed: "qa_report_pdf", title: "QA report (PDF)", icon: Presentation, needs: "results",
        description: "Cover, plain-language executive summary, quality score, charts, coverage heatmap, one page per bug, appendices." },
      { kind: "bugs_pdf", listed: "bugs_pdf", title: "Bug report (PDF)", icon: Bug, needs: "bugs", description: "Every bug on its own page with the annotated screenshot." },
      { kind: "requirements", listed: "requirements_pdf", title: "Requirements document (PDF + Markdown)", icon: FileText, needs: "requirements",
        description: "Reverse-engineered stories, workflows and business rules." },
    ],
  },
  {
    group: "For the QA team",
    items: [
      { kind: "qa_xlsx", listed: "qa_xlsx", title: "Excel workbook", icon: FileSpreadsheet, needs: "results",
        description: "Summary, Site Profile, Requirements, User Stories, Test Cases, Results, Bugs, Permission Matrix, Traceability." },
      { kind: "traceability_csv", listed: "traceability_csv", title: "Traceability matrix (CSV)", icon: Network, needs: "testcases",
        description: "Requirement → story → test case → result → bug." },
      { kind: "jira_csv", listed: "jira_csv", title: "Jira import (CSV)", icon: Table2, needs: "bugs", description: "Summary, priority, description with steps, labels, component." },
      { kind: "trello_csv", listed: "trello_csv", title: "Trello import (CSV)", icon: Table2, needs: "bugs", description: "One card per bug with labels for severity and priority." },
    ],
  },
  {
    group: "For developers",
    items: [
      { kind: "pytest_zip", listed: "pytest_zip", title: "pytest + Selenium suite (ZIP)", icon: Code2, needs: "testcases",
        description: "Page Object Model suite with its own README; recorded tests replay QA Pilot's exact actions." },
      { kind: "gherkin_zip", listed: "gherkin_zip", title: "Gherkin feature files (ZIP)", icon: GitBranch, needs: "testcases", description: "Approved test cases as .feature files." },
      { kind: "testcases_xlsx", listed: "testcases_xlsx", title: "Test cases (Excel)", icon: FileSpreadsheet, needs: "testcases", description: "Test cases, stories and rules only." },
    ],
  },
];

function size(bytes: number) {
  return bytes > 1e6 ? `${(bytes / 1e6).toFixed(1)} MB` : `${Math.max(1, Math.round(bytes / 1e3))} KB`;
}

export function Reports() {
  const { slug = "", runId = "" } = useParams();
  const qc = useQueryClient();
  const run = useQuery({ queryKey: ["run", slug, runId], queryFn: () => api.run(slug, runId) });
  const project = useQuery({ queryKey: ["project", slug], queryFn: () => api.project(slug) });
  const files = useQuery({ queryKey: ["exports", slug, runId], queryFn: () => api.exports(slug, runId) });
  const make = useMutation({
    mutationFn: (kind: ExportKind) => api.createExport(slug, runId, kind),
    onSuccess: (r) => { qc.invalidateQueries({ queryKey: ["exports", slug, runId] }); window.open(fileUrl(slug, runId, r.files[0]), "_blank"); },
    onError: (e: Error) => toast.error(e.message),
  });
  const available = run.data?.available ?? {};
  const crumbs = [{ label: "Projects", to: "/" }, { label: slug, to: `/projects/${slug}` }, { label: runId, to: `/projects/${slug}/runs/${runId}` }];
  const blur = project.data?.privacy_blur;

  return (
    <>
      <PageHeader crumbs={crumbs} title="Reports" description={<>Everything is saved in the run's <code className="font-mono text-xs">exports/</code> folder.
        Privacy blur: <b>{blur == null ? "auto" : blur ? "on" : "off"}</b> · branding from Settings · credentials never appear in exports.</>} />
      <div className="space-y-6">
        {ITEMS.map(({ group, items }) => (
          <section key={group}>
            <h2 className="mb-2 text-xs font-medium uppercase tracking-wider text-faint">{group}</h2>
            <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
              {items.map((it) => {
                const ready = Boolean(available[it.needs]);
                const existing = files.data?.find((f) => f.kind === it.listed);
                const busy = make.isPending && make.variables === it.kind;
                return (
                  <Card key={it.kind} className="flex flex-col gap-3 p-4">
                    <div className="flex items-start gap-3">
                      <span className="grid size-9 shrink-0 place-items-center rounded-lg bg-primary-soft text-blue-400"><it.icon className="size-4" /></span>
                      <div><div className="font-medium">{it.title}</div><p className="mt-0.5 text-xs text-muted">{it.description}</p></div>
                    </div>
                    <div className="mt-auto flex items-center gap-2">
                      <Button size="sm" onClick={() => make.mutate(it.kind)} disabled={!ready || make.isPending} title={ready ? undefined : `Needs ${it.needs} first`}>
                        {busy ? <Loader2 className="animate-spin" /> : <Download />} {existing ? "Regenerate" : "Generate"}
                      </Button>
                      {existing && (
                        <a className="truncate text-xs text-blue-400 hover:underline" href={fileUrl(slug, runId, existing.path)} target="_blank" rel="noreferrer">
                          {existing.path.split("/").pop()} · {size(existing.size)} · {timeAgo(new Date(existing.modified * 1000).toISOString())}
                        </a>
                      )}
                      {!ready && <span className="text-xs text-faint">needs {it.needs}</span>}
                    </div>
                  </Card>
                );
              })}
            </div>
          </section>
        ))}
      </div>
    </>
  );
}
