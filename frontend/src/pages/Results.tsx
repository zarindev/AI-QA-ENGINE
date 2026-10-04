import { useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import * as DialogPrimitive from "@radix-ui/react-dialog";
import { Bot, Bug as BugIcon, CheckCircle2, CircleSlash, Coins, Cpu, Film, ListChecks, Repeat, Timer, X, XCircle } from "lucide-react";
import { api, fileUrl, type Execution, type ResultKind, type TestRunResult } from "@/lib/api";
import { cn, pct } from "@/lib/utils";
import { PageHeader } from "@/components/PageHeader";
import { Ring } from "@/components/Ring";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { EmptyState, ErrorState } from "@/components/ui/states";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";

export const RESULT_TONE = { pass: "pass", fail: "fail", blocked: "warn", error: "neutral" } as const;
const METHOD_LABEL: Record<string, string> = { agent: "AI agent", replay: "replay", replay_healed: "replay → agent", rule: "rule runner" };

export function ResultIcon({ r, className }: { r: ResultKind; className?: string }) {
  if (r === "pass") return <CheckCircle2 className={cn("size-4 text-green-400", className)} />;
  if (r === "fail") return <XCircle className={cn("size-4 text-red-400", className)} />;
  if (r === "blocked") return <CircleSlash className={cn("size-4 text-amber-400", className)} />;
  return <CircleSlash className={cn("size-4 text-faint", className)} />;
}

export function Results() {
  const { slug = "", runId = "" } = useParams();
  const res = useQuery({ queryKey: ["results", slug, runId], queryFn: () => api.results(slug, runId), retry: false });
  const [filter, setFilter] = useState<"all" | ResultKind>("all");
  const [open, setOpen] = useState<TestRunResult | null>(null);
  const crumbs = [{ label: "Projects", to: "/" }, { label: slug, to: `/projects/${slug}` }, { label: runId, to: `/projects/${slug}/runs/${runId}` }];
  const rows = useMemo(() => (res.data?.results ?? []).filter((r) => filter === "all" || r.result === filter), [res.data, filter]);

  if (res.isLoading) return <Skeleton className="h-96 rounded-card" />;
  if (res.error)
    return (<><PageHeader crumbs={crumbs} title="Results" />
      {(res.error as { status?: number }).status === 404
        ? <EmptyState icon={ListChecks} title="No results yet" description="Approve test cases and run them." action={<Button asChild><Link to={`/projects/${slug}/runs/${runId}/tests`}>Go to test cases</Link></Button>} />
        : <ErrorState error={res.error} retry={() => res.refetch()} />}</>);
  const all = res.data!.results;
  const count = (k: ResultKind) => all.filter((r) => r.result === k).length;
  const executed = all.filter((r) => r.result === "pass" || r.result === "fail").length;
  const passRate = executed ? (count("pass") / executed) * 100 : null;
  const cost = all.reduce((s, r) => s + r.cost_usd, 0);
  const minutes = all.reduce((s, r) => s + r.duration_ms, 0) / 60000;

  return (
    <>
      <PageHeader crumbs={crumbs} title="Results" description={`${all.length} test cases · ${res.data!.mode} mode`}
        actions={<Button asChild><Link to={`/projects/${slug}/runs/${runId}/bugs`}><BugIcon /> Bugs</Link></Button>} />
      <div className="mb-5 grid gap-3 sm:grid-cols-2 xl:grid-cols-[auto_repeat(4,1fr)_1.3fr]">
        <Card className="flex items-center justify-center p-4"><Ring value={passRate} size={84} stroke={8} label="pass rate" /></Card>
        {(["pass", "fail", "blocked", "error"] as const).map((k) => (
          <button key={k} onClick={() => setFilter(filter === k ? "all" : k)} className="text-left">
            <Card className={cn("h-full p-4 transition hover:border-line-strong", filter === k && "border-primary shadow-[var(--glow)]")}>
              <div className="flex items-center gap-2 text-xs uppercase tracking-wider text-faint"><ResultIcon r={k} /> {k === "pass" ? "passed" : k === "fail" ? "failed" : k}</div>
              <div className="mt-1 text-3xl font-semibold">{count(k)}</div>
            </Card>
          </button>
        ))}
        <Card className="space-y-1.5 p-4 text-sm">
          <div className="flex items-center gap-2"><Coins className="size-4 text-amber-400" /> ${cost.toFixed(2)} Claude</div>
          <div className="flex items-center gap-2"><Timer className="size-4 text-blue-400" /> {minutes.toFixed(0)} min of browser time</div>
          <div className="flex items-center gap-2"><Repeat className="size-4 text-faint" /> failures re-run to confirm</div>
        </Card>
      </div>

      <Card className="overflow-hidden">
        <table className="w-full text-sm">
          <thead className="bg-primary-soft/30 text-left text-xs uppercase tracking-wide text-faint">
            <tr><th className="px-4 py-2.5">Result</th><th className="px-2">Test</th><th className="px-2">Technique</th><th className="px-2">Role</th><th className="px-2">Repro</th><th className="px-2">Ran by</th><th className="px-2 text-right">Cost</th><th className="px-4">Bugs</th></tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.test_case_id} className="cursor-pointer border-t border-line hover:bg-primary-soft/30" onClick={() => setOpen(r)}>
                <td className="px-4 py-2.5"><Badge tone={RESULT_TONE[r.result]}><ResultIcon r={r.result} className="size-3" />{r.result}</Badge></td>
                <td className="py-2.5 pr-2"><div className="font-medium">{r.title}</div><div className="font-mono text-[11px] text-faint">{r.test_case_id} · {r.module}</div></td>
                <td className="px-2"><Badge tone="primary">{r.technique.replace("_", " ")}</Badge></td>
                <td className="px-2 text-muted">{r.role || "—"}</td>
                <td className="px-2 font-mono text-xs">{r.reproducibility ? <span className={r.flaky ? "text-amber-400" : "text-red-400"}>{r.reproducibility}{r.flaky && " flaky"}</span> : "—"}</td>
                <td className="px-2 text-xs text-muted">{r.method === "rule" ? <Cpu className="mr-1 inline size-3.5" /> : <Bot className="mr-1 inline size-3.5" />}{METHOD_LABEL[r.method] ?? r.method}</td>
                <td className="px-2 text-right font-mono text-xs text-muted">{r.cost_usd ? `$${r.cost_usd.toFixed(3)}` : "—"}</td>
                <td className="px-4" onClick={(e) => e.stopPropagation()}>{r.bug_ids.map((b) => <Link key={b} to={`/projects/${slug}/runs/${runId}/bugs/${b}`} className="mr-1 font-mono text-xs text-blue-400 hover:underline">{b}</Link>)}</td>
              </tr>
            ))}
          </tbody>
        </table>
        {rows.length === 0 && <div className="p-8 text-center text-sm text-faint">No tests with this result.</div>}
      </Card>
      {open && <ExecutionDrawer slug={slug} runId={runId} result={open} onClose={() => setOpen(null)} />}
    </>
  );
}

function ExecutionDrawer({ slug, runId, result, onClose }: { slug: string; runId: string; result: TestRunResult; onClose: () => void }) {
  const ex = useQuery({ queryKey: ["executions", slug, runId, result.test_case_id], queryFn: () => api.executions(slug, runId, result.test_case_id) });
  return (
    <DialogPrimitive.Root open onOpenChange={(o) => !o && onClose()}>
      <DialogPrimitive.Portal>
        <DialogPrimitive.Overlay className="fixed inset-0 z-40 bg-black/50" />
        <DialogPrimitive.Content className="fixed inset-y-0 right-0 z-50 flex w-[min(960px,97vw)] flex-col border-l border-line-strong bg-panel-solid shadow-2xl">
          <div className="flex items-start justify-between gap-3 border-b border-line p-5">
            <div>
              <div className="flex items-center gap-2 font-mono text-xs text-faint">{result.test_case_id}<Badge tone={RESULT_TONE[result.result]}>{result.result}</Badge>{result.reproducibility && <Badge tone="fail">{result.reproducibility}</Badge>}</div>
              <DialogPrimitive.Title className="mt-1.5 text-lg font-semibold">{result.title}</DialogPrimitive.Title>
              <DialogPrimitive.Description className="text-xs text-muted">{result.module} · {result.role || "any role"} · {result.technique.replace("_", " ")}</DialogPrimitive.Description>
            </div>
            <DialogPrimitive.Close className="rounded-md p-1 text-muted hover:text-fg" aria-label="Close"><X className="size-5" /></DialogPrimitive.Close>
          </div>
          <div className="scrollbar-thin flex-1 overflow-y-auto p-5">
            {ex.isLoading && <Skeleton className="h-64" />}
            {ex.data && (
              <Tabs defaultValue="1">
                <TabsList>{ex.data.attempts.map((a) => <TabsTrigger key={a.attempt} value={String(a.attempt)}>Attempt {a.attempt} <span className={cn("ml-1", a.result === "fail" ? "text-red-400" : a.result === "pass" ? "text-green-400" : "text-faint")}>{a.result}</span></TabsTrigger>)}</TabsList>
                {ex.data.attempts.map((a) => <TabsContent key={a.attempt} value={String(a.attempt)} className="mt-4"><Attempt slug={slug} runId={runId} a={a} /></TabsContent>)}
              </Tabs>
            )}
          </div>
        </DialogPrimitive.Content>
      </DialogPrimitive.Portal>
    </DialogPrimitive.Root>
  );
}

function Attempt({ slug, runId, a }: { slug: string; runId: string; a: Execution }) {
  return (
    <div className="space-y-4">
      <Card className="grid gap-3 p-4 text-sm sm:grid-cols-2">
        <div><div className="text-xs uppercase tracking-wider text-faint">Expected</div><div className="mt-1">{a.expected || "—"}</div></div>
        <div><div className="text-xs uppercase tracking-wider text-faint">Actual</div><div className={cn("mt-1", a.result === "fail" && "text-red-300")}>{a.actual || a.reason}</div></div>
        <div className="text-xs text-muted sm:col-span-2">{a.reason} · confidence {pct(a.confidence)} · {METHOD_LABEL[a.method]} · ${a.token_usage.cost_usd.toFixed(3)}</div>
      </Card>
      {a.video && <video controls className="w-full rounded-xl border border-line" src={fileUrl(slug, runId, a.video)}><track kind="captions" /></video>}
      {a.auto_findings.length > 0 && (
        <Card className="p-4"><div className="mb-2 text-xs uppercase tracking-wider text-faint">Noticed while running</div>
          {a.auto_findings.map((f, i) => <div key={i} className="font-mono text-xs text-amber-300">step {f.step}: {f.title} — {f.detail}</div>)}</Card>
      )}
      <ol className="space-y-2">
        {a.steps.map((s) => (
          <li key={s.order} className={cn("grid grid-cols-[28px_1fr_180px] gap-3 rounded-xl border p-3", s.result === "fail" ? "border-red-500/40 bg-red-500/5" : s.result === "blocked" ? "border-amber-500/40" : "border-line")}>
            <span className="mt-0.5 font-mono text-xs text-faint">{s.order}</span>
            <div className="min-w-0 text-sm">
              <div><span className="font-medium">{s.action}</span> <span className="text-muted">{s.target}</span>{s.input && s.action !== "navigate" && <span className="ml-1 font-mono text-xs text-blue-300">“{s.input.slice(0, 80)}”</span>}</div>
              <div className="mt-1 text-xs text-muted">{s.observation}</div>
            </div>
            {s.screenshot_after ? (
              <a href={fileUrl(slug, runId, s.screenshot_after)} target="_blank" rel="noreferrer">
                <img loading="lazy" src={fileUrl(slug, runId, s.screenshot_after)} alt={`After step ${s.order}`} className="aspect-[16/10] w-full rounded-lg border border-line object-cover object-top" />
              </a>
            ) : <div className="grid aspect-[16/10] place-items-center rounded-lg border border-dashed border-line text-faint"><Film className="size-4" /></div>}
          </li>
        ))}
      </ol>
    </div>
  );
}
