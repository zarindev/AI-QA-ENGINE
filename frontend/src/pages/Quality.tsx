import { useState } from "react";
import { Link, useParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { ArrowRight, Gauge, GitCompareArrows, ShieldCheck } from "lucide-react";
import { api, type ComparedBug, type HeatCell } from "@/lib/api";
import { cn } from "@/lib/utils";
import { PageHeader } from "@/components/PageHeader";
import { Ring } from "@/components/Ring";
import { Badge, severityTone } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { EmptyState, ErrorState } from "@/components/ui/states";

const CELL_STYLE: Record<HeatCell["state"], string> = {
  pass: "bg-green-500/25 text-green-300 light:text-green-800",
  fail: "bg-red-500/30 text-red-300 light:text-red-800",
  warn: "bg-amber-500/25 text-amber-300 light:text-amber-800",
  untested: "bg-slate-500/10 text-faint",
};
const STATUS_LABEL: Record<ComparedBug["status"], string> = { new: "New", fixed: "Fixed", reappeared: "Reappeared", still_open: "Still open" };
const STATUS_TONE = { new: "fail", fixed: "pass", reappeared: "warn", still_open: "neutral" } as const;

export function Quality() {
  const { slug = "", runId = "" } = useParams();
  const q = useQuery({ queryKey: ["quality", slug, runId], queryFn: () => api.quality(slug, runId), retry: false });
  const crumbs = [{ label: "Projects", to: "/" }, { label: slug, to: `/projects/${slug}` }, { label: runId, to: `/projects/${slug}/runs/${runId}` }];

  if (q.isLoading) return <Skeleton className="h-96 rounded-card" />;
  if (q.error)
    return (<><PageHeader crumbs={crumbs} title="Coverage & quality" />
      {(q.error as { status?: number }).status === 404
        ? <EmptyState icon={Gauge} title="No score yet" description="The Quality Score is calculated after the approved tests run." />
        : <ErrorState error={q.error} retry={() => q.refetch()} />}</>);
  const { quality, heatmap } = q.data!;

  return (
    <>
      <PageHeader crumbs={crumbs} title="Coverage & quality" description="How much was tested, how much passed, and what changed since the last run."
        actions={<Button variant="secondary" asChild><Link to={`/projects/${slug}/runs/${runId}/permissions`}><ShieldCheck /> Permission matrix</Link></Button>} />

      <div className="mb-5 grid gap-4 lg:grid-cols-[280px_1fr]">
        <Card className="flex flex-col items-center justify-center gap-2 p-6">
          <Ring value={quality.score} size={150} stroke={12} label={quality.score == null ? "not measured" : `grade ${quality.grade}`} />
          <div className="text-xs uppercase tracking-wider text-faint">Quality score</div>
        </Card>
        <Card>
          <CardHeader><CardTitle>Score breakdown</CardTitle></CardHeader>
          <CardContent className="space-y-3">
            {quality.sub_scores.map((s) => (
              <div key={s.key} className="grid grid-cols-[130px_1fr_56px] items-center gap-3 text-sm">
                <span>{s.label}</span>
                <div className="h-2.5 overflow-hidden rounded-full bg-slate-500/15" title={s.note}>
                  {s.score != null && <div className={cn("h-full rounded-full", s.score >= 80 ? "bg-green-500" : s.score >= 55 ? "bg-amber-500" : "bg-red-500")} style={{ width: `${s.score}%` }} />}
                </div>
                <span className="text-right font-mono text-xs">{s.score == null ? "—" : s.score.toFixed(0)}</span>
                <span className="col-start-2 -mt-2 text-[11px] text-faint">
                  {s.note || `${s.passed}/${s.executed} passed`}{s.bugs > 0 && ` · ${s.bugs} open bug${s.bugs > 1 ? "s" : ""}`}
                </span>
              </div>
            ))}
            <p className="pt-1 text-[11px] text-faint">Formula: {quality.formula}.</p>
          </CardContent>
        </Card>
      </div>

      {heatmap && heatmap.cells.length > 0 && (
        <Card className="mb-5">
          <CardHeader><CardTitle>Coverage heatmap</CardTitle></CardHeader>
          <CardContent className="overflow-x-auto">
            <table className="text-xs">
              <thead>
                <tr><th className="sticky left-0 bg-panel-solid px-2 py-1.5 text-left font-medium text-faint">Module</th>
                  {heatmap.techniques.map((t) => <th key={t} className="px-1 py-1.5 font-medium text-faint"><div className="w-20 truncate" title={t}>{t.replace("_", " ")}</div></th>)}</tr>
              </thead>
              <tbody>
                {heatmap.modules.map((m) => (
                  <tr key={m}>
                    <td className="sticky left-0 bg-panel-solid px-2 py-1 font-medium">{m}</td>
                    {heatmap.techniques.map((t) => {
                      const c = heatmap.cells.find((x) => x.module === m && x.technique === t);
                      return (
                        <td key={t} className="p-0.5">
                          {c ? (
                            <div className={cn("grid h-9 place-items-center rounded-md font-mono", CELL_STYLE[c.state])}
                              title={`${m} · ${t}: ${c.passed} passed, ${c.failed} failed, ${c.other} blocked/error, ${c.total - c.passed - c.failed - c.other} not run\n${c.cases.join(", ")}`}>
                              {c.state === "untested" ? "–" : `${c.passed}/${c.total}`}
                            </div>
                          ) : <div className="h-9 rounded-md border border-dashed border-line" title="No test cases" />}
                        </td>
                      );
                    })}
                  </tr>
                ))}
              </tbody>
            </table>
            <div className="mt-3 flex flex-wrap gap-3 text-[11px] text-faint">
              {(["pass", "fail", "warn", "untested"] as const).map((k) => (
                <span key={k} className="flex items-center gap-1.5"><span className={cn("size-3 rounded", CELL_STYLE[k])} />{k === "warn" ? "partly / blocked" : k}</span>
              ))}
              <span className="flex items-center gap-1.5"><span className="size-3 rounded border border-dashed border-line" />no tests (gap)</span>
            </div>
          </CardContent>
        </Card>
      )}

      <Regression slug={slug} runId={runId} />
    </>
  );
}

function Regression({ slug, runId }: { slug: string; runId: string }) {
  const [base, setBase] = useState<string | undefined>();
  const cmp = useQuery({ queryKey: ["compare", slug, runId, base], queryFn: () => api.compare(slug, runId, base) });
  if (!cmp.data) return null;
  const { available, comparison } = cmp.data;
  return (
    <Card>
      <CardHeader className="flex flex-row flex-wrap items-center justify-between gap-2">
        <CardTitle className="flex items-center gap-2"><GitCompareArrows className="size-4" /> Regression comparison</CardTitle>
        {available.length > 0 && (
          <label className="flex items-center gap-2 text-xs text-muted">Compare with
            <select className="rounded-md border border-line bg-transparent px-2 py-1 font-mono text-xs" value={base ?? comparison?.base_run ?? ""} onChange={(e) => setBase(e.target.value)}>
              {available.map((r) => <option key={r} value={r}>{r}</option>)}
            </select>
          </label>
        )}
      </CardHeader>
      <CardContent>
        {!comparison ? (
          <p className="text-sm text-faint">This is the first run with results — run the tests again after a fix to see what is new, fixed or back.</p>
        ) : (
          <>
            <div className="mb-4 flex flex-wrap items-center gap-2 text-sm">
              <span className="font-mono text-xs text-faint">{comparison.base_run}</span><ArrowRight className="size-3.5 text-faint" /><span className="font-mono text-xs">{comparison.current_run}</span>
              {(Object.keys(STATUS_LABEL) as ComparedBug["status"][]).map((k) => <Badge key={k} tone={STATUS_TONE[k]}>{comparison.counts[k]} {STATUS_LABEL[k].toLowerCase()}</Badge>)}
            </div>
            <ul className="divide-y divide-line text-sm">
              {comparison.bugs.map((b) => (
                <li key={b.key} className="flex items-center gap-3 py-2">
                  <Badge tone={STATUS_TONE[b.status]} className="w-24 justify-center">{STATUS_LABEL[b.status]}</Badge>
                  <Badge tone={severityTone(b.severity)}>{b.severity}</Badge>
                  <span className="min-w-0 flex-1 truncate">{b.title}</span>
                  {b.current_id && <Link className="font-mono text-xs text-blue-400 hover:underline" to={`/projects/${slug}/runs/${runId}/bugs/${b.current_id}`}>{b.current_id}</Link>}
                </li>
              ))}
            </ul>
          </>
        )}
      </CardContent>
    </Card>
  );
}
