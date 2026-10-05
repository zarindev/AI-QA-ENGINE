import { useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { useMutation, useQuery } from "@tanstack/react-query";
import { AnimatePresence, motion } from "framer-motion";
import { toast } from "sonner";
import {
  AlertTriangle, Brain, Bug as BugIcon, ClipboardList, Coins, Gauge, ListChecks, ExternalLink, FileText, Image as ImageIcon, Loader2, Network, Radio, RotateCcw, ShieldBan, Square,
} from "lucide-react";
import { api, fileUrl, type Run } from "@/lib/api";
import { DOMAIN_LABELS, duration, pct } from "@/lib/utils";
import { useRunEvents, type RunEvent } from "@/hooks/useRunEvents";
import { PageHeader } from "@/components/PageHeader";
import { StageStepper } from "@/components/StageStepper";
import { Badge, severityTone, statusTone } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Progress } from "@/components/ui/progress";
import { Skeleton } from "@/components/ui/skeleton";
import { EmptyState, ErrorState } from "@/components/ui/states";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";

export function RunOverview() {
  const { slug = "", runId = "" } = useParams();
  const run = useQuery({ queryKey: ["run", slug, runId], queryFn: () => api.run(slug, runId), refetchInterval: (q) => (q.state.data?.running ? 3000 : false) });
  const live = run.data?.running || run.data?.status === "pending";
  const { events } = useRunEvents(slug, runId, true);

  const cancel = useMutation({ mutationFn: () => api.cancelRun(slug, runId), onSuccess: () => toast.info("Stopping after the current page…"), onError: (e: Error) => toast.error(e.message) });
  const resume = useMutation({ mutationFn: () => api.resumeRun(slug, runId), onSuccess: () => { toast.success("Resumed"); run.refetch(); }, onError: (e: Error) => toast.error(e.message) });

  if (run.isLoading) return <Skeleton className="h-96 rounded-card" />;
  if (run.error) return <ErrorState error={run.error} retry={() => run.refetch()} />;
  const r = run.data!;
  const done = r.available ?? {};

  return (
    <>
      <PageHeader
        crumbs={[{ label: "Projects", to: "/" }, { label: slug, to: `/projects/${slug}` }]}
        title={<span className="flex items-center gap-3">Run <span className="font-mono text-xl text-muted">{r.id}</span></span>}
        description={
          <span className="flex flex-wrap items-center gap-2">
            <Badge tone={statusTone(r.status)}>{live && <Loader2 className="animate-spin" />}{r.status}</Badge>
            <Badge tone={r.mode === "full" ? "warn" : "pass"}>{r.mode} mode</Badge>
            <span>{duration(r.started_at, r.finished_at)}</span>
            {r.token_usage.requests > 0 && <span className="flex items-center gap-1"><Coins className="size-3.5" /> ${r.token_usage.cost_usd.toFixed(3)} · {r.token_usage.requests} AI calls</span>}
          </span>
        }
        actions={
          <>
            {done.profile && <Button variant="secondary" asChild><Link to={`/projects/${slug}/runs/${runId}/profile`}><Brain /> Site profile</Link></Button>}
            {done.model && <Button variant="secondary" asChild><Link to={`/projects/${slug}/runs/${runId}/model`}><Network /> Site model</Link></Button>}
            {done.requirements && <Button variant="secondary" asChild><Link to={`/projects/${slug}/runs/${runId}/requirements`}><FileText /> Requirements</Link></Button>}
            {done.bugs && <Button asChild><Link to={`/projects/${slug}/runs/${runId}/bugs`}><BugIcon /> Bugs</Link></Button>}
            {done.results && <Button variant="secondary" asChild><Link to={`/projects/${slug}/runs/${runId}/results`}><ClipboardList /> Results</Link></Button>}
            {done.results && <Button variant="secondary" asChild><Link to={`/projects/${slug}/runs/${runId}/quality`}><Gauge /> Quality</Link></Button>}
            {done.testcases && <Button variant={done.results ? "secondary" : "primary"} asChild><Link to={`/projects/${slug}/runs/${runId}/tests`}><ListChecks /> Review test cases</Link></Button>}
            {done.report && <Button variant="ghost" asChild><a href={fileUrl(slug, runId, "exports/crawl_report.html")} target="_blank" rel="noreferrer"><FileText /> HTML report</a></Button>}
            {live && <Button variant="danger" onClick={() => cancel.mutate()}><Square /> Stop</Button>}
            {["interrupted", "failed", "cancelled"].includes(r.status) && <Button onClick={() => resume.mutate()} disabled={resume.isPending}><RotateCcw /> Resume</Button>}
          </>
        }
      />

      <div className="mb-5 flex items-center gap-3">
        <Progress value={r.progress} className="h-2 flex-1" tone={r.status === "failed" ? "fail" : r.status === "completed" ? "pass" : "primary"} />
        <span className="w-12 text-right font-mono text-sm">{Math.round(r.progress)}%</span>
      </div>
      {r.error && <div className="mb-5"><ErrorState error={new Error(r.error)} /></div>}
      <StageStepper run={r} />

      <div className="mt-6 grid gap-4 xl:grid-cols-[1.4fr_1fr]">
        <LiveView slug={slug} runId={runId} events={events} live={!!live} />
        <Narration events={events} live={!!live} run={r} />
      </div>

      {done.pages && <RunData slug={slug} runId={runId} />}
    </>
  );
}

function LiveView({ slug, runId, events, live }: { slug: string; runId: string; events: RunEvent[]; live: boolean }) {
  const shots = events.filter((e) => e.screenshot);
  const latest = shots[shots.length - 1];
  return (
    <Card className="overflow-hidden">
      <CardHeader className="pb-1">
        <CardTitle className="flex items-center gap-2">{live ? <Radio className="size-4 animate-pulse text-red-400" /> : <ImageIcon className="size-4" />} {live ? "Live browser" : "Last screen"}</CardTitle>
        {latest?.role && <Badge tone="primary">{latest.role}</Badge>}
        {latest?.test_id && !latest.role && <Badge tone="primary">{latest.test_id}</Badge>}
      </CardHeader>
      <CardContent>
        <div className="relative aspect-[16/10] overflow-hidden rounded-xl border border-line bg-black/40">
          <AnimatePresence mode="popLayout">
            {latest ? (
              <motion.img key={latest.screenshot} src={fileUrl(slug, runId, latest.screenshot!)} alt={`Screenshot of ${latest.url}`}
                initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} className="absolute inset-0 size-full object-contain object-top" />
            ) : (
              <div className="grid size-full place-items-center text-sm text-faint">{live ? "Waiting for the first page…" : "No screenshots"}</div>
            )}
          </AnimatePresence>
        </div>
        {latest && <div className="mt-2 truncate font-mono text-xs text-muted">{latest.url}</div>}
      </CardContent>
    </Card>
  );
}

function Ticker({ events }: { events: RunEvent[] }) {
  // the latest result per test (a run can have several execution passes)
  const latest = new Map<string, string>();
  for (const e of events) if (e.test_id && e.result) latest.set(e.test_id, e.result);
  if (latest.size === 0) return null;
  const n = (k: string) => [...latest.values()].filter((v) => v === k).length;
  return (
    <div className="flex items-center gap-3 font-mono text-xs">
      <span className="text-green-400">✓ {n("pass")}</span><span className="text-red-400">✗ {n("fail")}</span>
      <span className="text-amber-400">⊘ {n("blocked")}</span>{n("error") > 0 && <span className="text-faint">! {n("error")}</span>}
    </div>
  );
}

function Narration({ events, live, run }: { events: RunEvent[]; live: boolean; run: Run }) {
  const items = events.filter((e) => e.message && e.type !== "usage").slice(-60).reverse();
  return (
    <Card>
      <CardHeader className="pb-1"><CardTitle>What QA Pilot is doing</CardTitle><Ticker events={events} />{live && !events.some((e) => e.result) && <span className="text-xs text-faint">{run.message}</span>}</CardHeader>
      <CardContent>
        <ol className="scrollbar-thin max-h-[340px] space-y-1.5 overflow-y-auto pr-1">
          {items.length === 0 && <li className="text-sm text-faint">No events yet.</li>}
          {items.map((e, i) => (
            <li key={`${e.at}-${i}`} className="flex gap-2 text-[13px]">
              <span className="w-14 shrink-0 font-mono text-[11px] text-faint">{new Date(e.at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit", hourCycle: "h23" })}</span>
              <span className={e.type === "stage_done" || e.result === "pass" ? "text-green-400" : e.type === "run_failed" || e.result === "fail" ? "text-red-400" : e.result === "blocked" ? "text-amber-400" : "text-muted"}>{e.error ?? e.message}</span>
            </li>
          ))}
        </ol>
      </CardContent>
    </Card>
  );
}

function RunData({ slug, runId }: { slug: string; runId: string }) {
  const pages = useQuery({ queryKey: ["pages", slug, runId], queryFn: () => api.pages(slug, runId) });
  const findings = useQuery({ queryKey: ["findings", slug, runId], queryFn: () => api.findings(slug, runId) });
  const profile = useQuery({ queryKey: ["profile", slug, runId], queryFn: () => api.profile(slug, runId), retry: false });
  const [role, setRole] = useState<string>("all");
  const roles = useMemo(() => ["all", ...(pages.data?.roles.map((r) => r.role) ?? [])], [pages.data]);
  const shown = pages.data?.pages.filter((p) => role === "all" || p.role === role) ?? [];

  return (
    <div className="mt-6">
      {profile.data && (
        <Card className="mb-4 p-5">
          <div className="flex flex-wrap items-center gap-4">
            <div className="grid size-12 place-items-center rounded-2xl bg-primary-soft text-primary"><Brain className="size-6" /></div>
            <div className="min-w-0 flex-1">
              <div className="text-xs uppercase tracking-wider text-faint">Detected</div>
              <div className="text-lg font-semibold">{DOMAIN_LABELS[profile.data.domain] ?? profile.data.domain} <span className="font-normal text-muted">· {profile.data.sub_type}</span></div>
              <div className="text-sm text-muted">{profile.data.summary}</div>
            </div>
            <Badge tone={profile.data.method === "ai" ? "primary" : "warn"}>{profile.data.method === "ai" ? "Claude analysis" : "Offline heuristic"} · {pct(profile.data.confidence)}</Badge>
            <Button variant="secondary" asChild><Link to={`/projects/${slug}/runs/${runId}/profile`}>Open profile</Link></Button>
          </div>
        </Card>
      )}
      <Tabs defaultValue="pages">
        <TabsList>
          <TabsTrigger value="pages">Pages {pages.data && <span className="ml-1 text-faint">{pages.data.pages.length}</span>}</TabsTrigger>
          <TabsTrigger value="findings">Findings {findings.data && <span className="ml-1 text-faint">{findings.data.findings.length}</span>}</TabsTrigger>
          <TabsTrigger value="safety">Safe Mode log {pages.data && <span className="ml-1 text-faint">{pages.data.blocked_actions.length}</span>}</TabsTrigger>
        </TabsList>

        <TabsContent value="pages" className="mt-4">
          {pages.isLoading && <Skeleton className="h-48" />}
          {pages.data && (
            <>
              <div className="mb-3 flex flex-wrap gap-1.5">
                {roles.map((r) => (
                  <button key={r} onClick={() => setRole(r)} className={`rounded-full border px-3 py-1 text-xs ${role === r ? "border-primary bg-primary-soft text-fg" : "border-line text-muted hover:text-fg"}`}>
                    {r} {r !== "all" && <span className="text-faint">{pages.data.pages.filter((p) => p.role === r).length}</span>}
                  </button>
                ))}
              </div>
              <div className="mb-3 flex flex-wrap gap-2">
                {pages.data.roles.filter((r) => r.login_ok === false).map((r) => (
                  <Badge key={r.role} tone="fail"><AlertTriangle /> {r.role}: {r.login_message}</Badge>
                ))}
              </div>
              <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3 2xl:grid-cols-4">
                {shown.map((p) => (
                  <a key={p.id} href={fileUrl(slug, runId, p.screenshot)} target="_blank" rel="noreferrer" className="group">
                    <Card className="overflow-hidden transition group-hover:border-primary/50">
                      <img loading="lazy" src={fileUrl(slug, runId, p.thumbnail)} alt={`Screenshot of ${p.title || p.url}`} className="aspect-[16/10] w-full border-b border-line object-cover object-top" />
                      <div className="p-3">
                        <div className="flex items-center justify-between gap-2">
                          <div className="truncate text-sm font-medium">{p.title || "(no title)"}</div>
                          <Badge tone={p.status_code && p.status_code >= 400 ? "fail" : "neutral"}>{p.status_code ?? "—"}</Badge>
                        </div>
                        <div className="truncate font-mono text-[11px] text-faint">{p.url_template}</div>
                        <div className="mt-1.5 flex flex-wrap gap-1 text-[11px] text-muted">
                          <span>{p.role}</span>·<span>{p.element_count} elements</span>·<span>{p.forms.length} forms</span>
                          {p.load_time_ms != null && <>·<span>{(p.load_time_ms / 1000).toFixed(1)}s</span></>}
                        </div>
                      </div>
                    </Card>
                  </a>
                ))}
              </div>
            </>
          )}
        </TabsContent>

        <TabsContent value="findings" className="mt-4">
          {findings.data && findings.data.findings.length === 0 && <EmptyState icon={ShieldBan} title="No automatic findings" description="Functional bugs are found by the generated tests in later stages." />}
          {findings.data && findings.data.findings.length > 0 && (
            <Card className="overflow-hidden">
              <table className="w-full text-sm">
                <thead className="bg-primary-soft/30 text-left text-xs uppercase tracking-wide text-faint">
                  <tr><th className="px-4 py-2.5">ID</th><th className="px-4 py-2.5">Severity</th><th className="px-4 py-2.5">Finding</th><th className="px-4 py-2.5">Where</th><th className="px-4 py-2.5">Seen</th></tr>
                </thead>
                <tbody>
                  {findings.data.findings.map((f) => (
                    <tr key={f.id} className="border-t border-line align-top">
                      <td className="px-4 py-3 font-mono text-xs">{f.id}</td>
                      <td className="px-4 py-3"><Badge tone={severityTone(f.severity)}>{f.severity}</Badge></td>
                      <td className="px-4 py-3"><div className="font-medium">{f.title}</div><div className="mt-0.5 break-all font-mono text-[11.5px] text-muted">{f.detail}</div></td>
                      <td className="max-w-[260px] px-4 py-3"><a href={f.page_url} target="_blank" rel="noreferrer" className="flex items-center gap-1 truncate font-mono text-xs text-blue-400 hover:underline">{f.page_url}<ExternalLink className="size-3 shrink-0" /></a><div className="text-xs text-faint">{f.role}</div></td>
                      <td className="px-4 py-3 text-muted">{f.data.occurrences ?? 1}×</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </Card>
          )}
        </TabsContent>

        <TabsContent value="safety" className="mt-4">
          {pages.data && pages.data.blocked_actions.length === 0 && <EmptyState icon={ShieldBan} title="Nothing was blocked" description="Safe Mode did not need to stop any action in this run." />}
          {pages.data && pages.data.blocked_actions.length > 0 && (
            <Card className="divide-y divide-line">
              {pages.data.blocked_actions.map((b, i) => (
                <div key={i} className="flex flex-wrap items-center gap-3 px-4 py-2.5 text-sm">
                  <ShieldBan className="size-4 text-amber-400" /><Badge>{b.role}</Badge><span className="font-medium">{b.action}</span>
                  <span className="truncate font-mono text-xs text-muted">{b.target}</span><span className="ml-auto text-xs text-faint">{b.reason}</span>
                </div>
              ))}
            </Card>
          )}
        </TabsContent>
      </Tabs>
    </div>
  );
}
