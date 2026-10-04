import { useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import {
  ArrowRight, Check, CheckCheck, FileDown, FileText, ListChecks, Loader2, Pencil, RotateCcw, Scale, Sparkles, Users, Workflow as WorkflowIcon, X,
} from "lucide-react";
import { api, fileUrl, type BusinessRule, type Requirements as Req, type Workflow } from "@/lib/api";
import { cn, pct } from "@/lib/utils";
import { PageHeader } from "@/components/PageHeader";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input, Label } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { EmptyState, ErrorState } from "@/components/ui/states";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";

const CATEGORY_TONE: Record<string, "primary" | "pass" | "fail" | "warn" | "info" | "neutral"> = {
  calculation: "warn", permission: "fail", validation: "info", state: "primary", data_integrity: "pass", scheduling: "primary", other: "neutral",
};

export function Requirements() {
  const { slug = "", runId = "" } = useParams();
  const qc = useQueryClient();
  const req = useQuery({ queryKey: ["requirements", slug, runId], queryFn: () => api.requirements(slug, runId), retry: false });
  const exports = useQuery({ queryKey: ["exports", slug, runId], queryFn: () => api.exports(slug, runId) });
  const exportPdf = useMutation({
    mutationFn: () => api.createExport(slug, runId, "requirements"),
    onSuccess: () => { toast.success("Requirements document exported"); qc.invalidateQueries({ queryKey: ["exports", slug, runId] }); },
    onError: (e: Error) => toast.error(e.message),
  });
  const crumbs = [{ label: "Projects", to: "/" }, { label: slug, to: `/projects/${slug}` }, { label: runId, to: `/projects/${slug}/runs/${runId}` }];

  if (req.isLoading) return <Skeleton className="h-96 rounded-card" />;
  if (req.error)
    return (
      <>
        <PageHeader crumbs={crumbs} title="Requirements" />
        {(req.error as { status?: number }).status === 404
          ? <EmptyState icon={FileText} title="No requirements yet" description="They are written after the site model is built." />
          : <ErrorState error={req.error} retry={() => req.refetch()} />}
      </>
    );
  const data = req.data!;
  const pdf = exports.data?.find((e) => e.kind === "requirements_pdf");
  const md = exports.data?.find((e) => e.kind === "requirements_md");

  return (
    <>
      <PageHeader
        crumbs={crumbs}
        title="Reverse-engineered requirements"
        description={<>What the app should do, inferred from what QA Pilot saw. Confirm the business rules you agree with — only confirmed rules drive business-rule tests.{" "}
          <Badge tone={data.method === "ai" ? "primary" : "warn"} className="ml-1"><Sparkles /> {data.method === "ai" ? "Written by Claude" : "Offline heuristic"}</Badge></>}
        actions={
          <>
            {pdf && <Button variant="ghost" asChild><a href={fileUrl(slug, runId, pdf.path)} target="_blank" rel="noreferrer"><FileDown /> PDF</a></Button>}
            {md && <Button variant="ghost" asChild><a href={fileUrl(slug, runId, md.path)} target="_blank" rel="noreferrer"><FileDown /> Markdown</a></Button>}
            <Button variant="secondary" onClick={() => exportPdf.mutate()} disabled={exportPdf.isPending}>
              {exportPdf.isPending ? <Loader2 className="animate-spin" /> : <FileText />} {pdf ? "Re-export document" : "Export document"}
            </Button>
            <Button asChild><Link to={`/projects/${slug}/runs/${runId}/tests`}><ListChecks /> Test cases <ArrowRight /></Link></Button>
          </>
        }
      />
      <Tabs defaultValue="rules">
        <TabsList>
          <TabsTrigger value="rules"><Scale className="mr-1 inline size-3.5" />Business rules <span className="ml-1 text-faint">{data.rules.length}</span></TabsTrigger>
          <TabsTrigger value="stories"><Users className="mr-1 inline size-3.5" />User stories <span className="ml-1 text-faint">{data.stories.length}</span></TabsTrigger>
          <TabsTrigger value="workflows"><WorkflowIcon className="mr-1 inline size-3.5" />Workflows <span className="ml-1 text-faint">{data.workflows.length}</span></TabsTrigger>
        </TabsList>
        <TabsContent value="rules" className="mt-4"><Rules slug={slug} runId={runId} data={data} /></TabsContent>
        <TabsContent value="stories" className="mt-4"><Stories data={data} /></TabsContent>
        <TabsContent value="workflows" className="mt-4 space-y-4">
          {data.workflows.length === 0 && <EmptyState icon={WorkflowIcon} title="No workflows found" />}
          {data.workflows.map((w) => <WorkflowCard key={w.id} w={w} />)}
        </TabsContent>
      </Tabs>
    </>
  );
}

function Rules({ slug, runId, data }: { slug: string; runId: string; data: Req }) {
  const qc = useQueryClient();
  const [filter, setFilter] = useState<"all" | "proposed" | "confirmed" | "rejected">("all");
  const refresh = () => qc.invalidateQueries({ queryKey: ["requirements", slug, runId] });
  const bulk = useMutation({
    mutationFn: (ids: string[]) => api.bulkRules(slug, runId, ids, "confirmed"),
    onSuccess: (r) => { toast.success(`${r.updated} rules confirmed`); refresh(); },
    onError: (e: Error) => toast.error(e.message),
  });
  const counts = useMemo(() => ({
    proposed: data.rules.filter((r) => r.status === "proposed").length,
    confirmed: data.rules.filter((r) => r.status === "confirmed" || r.status === "edited").length,
    rejected: data.rules.filter((r) => r.status === "rejected").length,
  }), [data.rules]);
  const strong = data.rules.filter((r) => r.status === "proposed" && r.confidence >= 0.8);
  const shown = data.rules.filter((r) => filter === "all" || (filter === "confirmed" ? ["confirmed", "edited"].includes(r.status) : r.status === filter));

  return (
    <>
      <div className="mb-4 flex flex-wrap items-center gap-2">
        {(["all", "proposed", "confirmed", "rejected"] as const).map((f) => (
          <button key={f} onClick={() => setFilter(f)} className={cn("rounded-full border px-3 py-1 text-xs capitalize", filter === f ? "border-primary bg-primary-soft text-fg" : "border-line text-muted hover:text-fg")}>
            {f} <span className="text-faint">{f === "all" ? data.rules.length : counts[f]}</span>
          </button>
        ))}
        {strong.length > 0 && (
          <Button size="sm" variant="secondary" className="ml-auto" onClick={() => bulk.mutate(strong.map((r) => r.id))} disabled={bulk.isPending}>
            <CheckCheck /> Confirm {strong.length} high-confidence rules (≥ 80%)
          </Button>
        )}
      </div>
      {counts.confirmed > 0 && (
        <div className="mb-4 flex items-center justify-between gap-3 rounded-xl border border-primary/40 bg-primary-soft px-4 py-3 text-sm">
          <span>{counts.confirmed} confirmed rule{counts.confirmed === 1 ? "" : "s"} will get business-rule tests the next time test cases are generated.</span>
          <Button size="sm" asChild><Link to={`/projects/${slug}/runs/${runId}/tests`}>Go to test cases <ArrowRight /></Link></Button>
        </div>
      )}
      <div className="space-y-2.5">
        {shown.map((r) => <RuleCard key={r.id} rule={r} slug={slug} runId={runId} onChange={refresh} />)}
        {shown.length === 0 && <EmptyState icon={Scale} title="Nothing here" description="No rules match this filter." />}
      </div>
    </>
  );
}

function RuleCard({ rule, slug, runId, onChange }: { rule: BusinessRule; slug: string; runId: string; onChange: () => void }) {
  const [editing, setEditing] = useState(false);
  const [statement, setStatement] = useState(rule.statement);
  const [condition, setCondition] = useState(rule.condition);
  const update = useMutation({
    mutationFn: (body: Parameters<typeof api.updateRule>[3]) => api.updateRule(slug, runId, rule.id, body),
    onSuccess: () => { setEditing(false); onChange(); },
    onError: (e: Error) => toast.error(e.message),
  });
  const confirmed = rule.status === "confirmed" || rule.status === "edited";
  return (
    <Card className={cn("p-4 transition", confirmed && "border-green-500/30", rule.status === "rejected" && "opacity-55")}>
      <div className="flex flex-wrap items-start gap-3">
        <span className="mt-0.5 font-mono text-xs text-faint">{rule.id}</span>
        <div className="min-w-0 flex-1">
          {editing ? (
            <div className="space-y-2">
              <div><Label htmlFor={`st-${rule.id}`}>Rule</Label><Input id={`st-${rule.id}`} value={statement} onChange={(e) => setStatement(e.target.value)} /></div>
              <div><Label htmlFor={`co-${rule.id}`}>Testable condition</Label><Input id={`co-${rule.id}`} className="font-mono text-xs" value={condition} onChange={(e) => setCondition(e.target.value)} /></div>
              <div className="flex gap-2">
                <Button size="sm" onClick={() => update.mutate({ statement, condition, status: "confirmed" })} disabled={update.isPending}><Check /> Save & confirm</Button>
                <Button size="sm" variant="ghost" onClick={() => setEditing(false)}>Cancel</Button>
              </div>
            </div>
          ) : (
            <>
              <div className="text-[14px] font-medium">{rule.statement}</div>
              {rule.condition && <code className="mt-1.5 block rounded-md bg-slate-500/10 px-2 py-1 font-mono text-[11.5px] text-muted">{rule.condition}</code>}
              <div className="mt-2 flex flex-wrap items-center gap-2 text-xs text-faint">
                <Badge tone={CATEGORY_TONE[rule.category] ?? "neutral"}>{rule.category.replace("_", " ")}</Badge>
                {rule.entity && <Badge>{rule.entity}</Badge>}
                <span className="flex items-center gap-1.5">confidence
                  <span className="inline-block h-1.5 w-14 rounded-full bg-slate-500/20"><span className="block h-full rounded-full bg-primary" style={{ width: pct(rule.confidence) }} /></span>
                  {pct(rule.confidence)}</span>
                <span className="truncate">· {rule.source}</span>
              </div>
            </>
          )}
        </div>
        {!editing && (
          <div className="flex items-center gap-1.5">
            {confirmed && <Badge tone="pass"><Check /> {rule.status === "edited" ? "Confirmed (edited)" : "Confirmed"}</Badge>}
            {rule.status === "rejected" && <Badge>Rejected</Badge>}
            {rule.status === "proposed" && (
              <Button size="sm" onClick={() => update.mutate({ status: "confirmed" })} disabled={update.isPending}><Check /> Confirm</Button>
            )}
            <Button size="icon" variant="ghost" aria-label="Edit rule" onClick={() => setEditing(true)}><Pencil /></Button>
            {rule.status !== "rejected"
              ? <Button size="icon" variant="ghost" aria-label="Reject rule" onClick={() => update.mutate({ status: "rejected" })}><X /></Button>
              : <Button size="icon" variant="ghost" aria-label="Restore rule" onClick={() => update.mutate({ status: "proposed" })}><RotateCcw /></Button>}
          </div>
        )}
      </div>
    </Card>
  );
}

function Stories({ data }: { data: Req }) {
  const roles = [...new Set(data.stories.map((s) => s.role))];
  if (data.stories.length === 0) return <EmptyState icon={Users} title="No user stories" />;
  return (
    <div className="grid gap-4 lg:grid-cols-2">
      {roles.map((role) => (
        <Card key={role}>
          <CardHeader><CardTitle className="flex items-center gap-2"><Users className="size-4" /> {role}</CardTitle><Badge>{data.stories.filter((s) => s.role === role).length} stories</Badge></CardHeader>
          <CardContent className="space-y-3">
            {data.stories.filter((s) => s.role === role).map((s) => (
              <div key={s.id} className="rounded-lg border border-line p-3">
                <div className="flex items-start gap-2"><span className="font-mono text-[11px] text-faint">{s.id}</span><span className="text-sm">{s.story}</span></div>
                {s.acceptance_criteria.length > 0 && (
                  <ul className="mt-2 space-y-1 pl-6 text-xs text-muted">
                    {s.acceptance_criteria.map((a, i) => <li key={i} className="list-disc">{a}</li>)}
                  </ul>
                )}
                {s.module && <Badge className="mt-2" tone="primary">{s.module}</Badge>}
              </div>
            ))}
          </CardContent>
        </Card>
      ))}
    </div>
  );
}

function WorkflowCard({ w }: { w: Workflow }) {
  return (
    <Card>
      <CardHeader>
        <div><CardTitle className="flex items-center gap-2"><span className="font-mono text-xs text-faint">{w.id}</span> {w.name}</CardTitle>
          {w.description && <p className="mt-1 text-sm text-muted">{w.description}</p>}</div>
        <div className="flex flex-wrap gap-1">{w.roles.map((r) => <Badge key={r}>{r}</Badge>)}</div>
      </CardHeader>
      <CardContent className="grid gap-5 lg:grid-cols-2">
        <div>
          <div className="mb-2 text-xs uppercase tracking-wider text-faint">States</div>
          <div className="flex flex-wrap items-center gap-1.5">
            {w.states.map((s, i) => (
              <span key={s} className="flex items-center gap-1.5">
                <span className="rounded-lg border border-primary/40 bg-primary-soft px-2.5 py-1 text-[13px]">{s}</span>
                {i < w.states.length - 1 && <ArrowRight className="size-3.5 text-faint" />}
              </span>
            ))}
          </div>
          {w.transitions.length > 0 && (
            <table className="mt-4 w-full text-sm">
              <thead className="text-left text-[11px] uppercase tracking-wide text-faint"><tr><th className="pb-1.5">From</th><th className="pb-1.5">To</th><th className="pb-1.5">Action</th><th className="pb-1.5" /></tr></thead>
              <tbody>
                {w.transitions.map((t, i) => (
                  <tr key={i} className="border-t border-line">
                    <td className="py-1.5">{t.from_state}</td><td>{t.to_state}</td><td className="text-muted">{t.action}</td>
                    <td className="text-right">{t.allowed ? <Badge tone="pass">allowed</Badge> : <Badge tone="fail">must be refused</Badge>}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
        {w.steps.length > 0 && (
          <div>
            <div className="mb-2 text-xs uppercase tracking-wider text-faint">Steps</div>
            <ol className="space-y-1.5">
              {w.steps.map((s) => (
                <li key={s.order} className="flex gap-2 text-sm">
                  <span className="grid size-5 shrink-0 place-items-center rounded-full bg-slate-500/15 text-[11px]">{s.order}</span>
                  <span>{s.action}{s.role && <span className="text-faint"> · {s.role}</span>}{s.page && <span className="ml-1 font-mono text-[11px] text-faint">{s.page}</span>}</span>
                </li>
              ))}
            </ol>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
