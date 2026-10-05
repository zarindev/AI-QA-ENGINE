import { useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { motion } from "framer-motion";
import { toast } from "sonner";
import {
  AlertOctagon, ArrowLeft, Bug as BugIcon, Check, CheckCheck, Clapperboard, ClipboardList, Eye, FileDown, Film, LayoutGrid, List, Loader2, Monitor,
  Play, Repeat, ScrollText, ShieldAlert, Wrench, X,
} from "lucide-react";
import { api, fileUrl, type BugStatus, type Severity } from "@/lib/api";
import { cn, pct } from "@/lib/utils";
import { PageHeader } from "@/components/PageHeader";
import { Badge, severityTone } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { EmptyState, ErrorState } from "@/components/ui/states";

const SEVERITIES: Severity[] = ["critical", "major", "minor", "trivial"];
const SEV_COLOR: Record<Severity, string> = { critical: "#DC2626", major: "#F59E0B", minor: "#38BDF8", trivial: "#64748B" };
const STATUS_TONE = { new: "primary", needs_review: "warn", confirmed: "fail", rejected: "neutral", fixed: "pass" } as const;
const STATUS_LABEL: Record<BugStatus, string> = { new: "New", needs_review: "Needs review", confirmed: "Confirmed", rejected: "Rejected", fixed: "Fixed" };

function useBugs(slug: string, runId: string) {
  return useQuery({ queryKey: ["bugs", slug, runId], queryFn: () => api.bugs(slug, runId), retry: false });
}

export function Bugs() {
  const { slug = "", runId = "" } = useParams();
  const bugs = useBugs(slug, runId);
  const [view, setView] = useState<"board" | "table">("board");
  const [queue, setQueue] = useState<"open" | "needs_review" | "closed">("open");
  const crumbs = [{ label: "Projects", to: "/" }, { label: slug, to: `/projects/${slug}` }, { label: runId, to: `/projects/${slug}/runs/${runId}` }];
  const list = useMemo(() => (bugs.data?.bugs ?? []).filter((b) =>
    queue === "needs_review" ? b.status === "needs_review" : queue === "closed" ? ["rejected", "fixed"].includes(b.status) : ["new", "confirmed"].includes(b.status)), [bugs.data, queue]);

  if (bugs.isLoading) return <Skeleton className="h-96 rounded-card" />;
  if (bugs.error)
    return (<><PageHeader crumbs={crumbs} title="Bugs" />{(bugs.error as { status?: number }).status === 404
      ? <EmptyState icon={BugIcon} title="No bugs yet" description="Bugs appear after the approved tests have run." /> : <ErrorState error={bugs.error} />}</>);
  const all = bugs.data!.bugs;
  const counts = { open: all.filter((b) => ["new", "confirmed"].includes(b.status)).length, needs_review: all.filter((b) => b.status === "needs_review").length, closed: all.filter((b) => ["rejected", "fixed"].includes(b.status)).length };

  return (
    <>
      <PageHeader crumbs={crumbs} title="Bugs" description="Every bug was reproduced by re-running its test; evidence is attached."
        actions={<>
          <Button variant="ghost" asChild><Link to={`/projects/${slug}/runs/${runId}/results`}><ClipboardList /> Results</Link></Button>
          <Button variant="secondary" asChild><Link to={`/projects/${slug}/runs/${runId}/reports`}><FileDown /> Reports</Link></Button>
          <div className="flex rounded-lg border border-line p-0.5">
            <button aria-label="Board view" onClick={() => setView("board")} className={cn("rounded-md p-1.5", view === "board" && "bg-primary-soft")}><LayoutGrid className="size-4" /></button>
            <button aria-label="Table view" onClick={() => setView("table")} className={cn("rounded-md p-1.5", view === "table" && "bg-primary-soft")}><List className="size-4" /></button>
          </div>
        </>} />
      <div className="mb-4 flex gap-2">
        {(["open", "needs_review", "closed"] as const).map((q) => (
          <button key={q} onClick={() => setQueue(q)} className={cn("rounded-full border px-3 py-1 text-xs", queue === q ? "border-primary bg-primary-soft text-fg" : "border-line text-muted hover:text-fg")}>
            {q === "open" ? "Open" : q === "needs_review" ? "Needs review" : "Closed"} <span className="text-faint">{counts[q]}</span>
          </button>
        ))}
      </div>
      {list.length === 0 && <EmptyState icon={BugIcon} title={queue === "needs_review" ? "Nothing to review" : "No bugs here"} />}
      {list.length > 0 && view === "board" && (
        <div className="grid gap-4 lg:grid-cols-4">
          {SEVERITIES.map((sev) => {
            const col = list.filter((b) => b.severity === sev);
            return (
              <div key={sev}>
                <div className="mb-2 flex items-center gap-2 px-1 text-sm font-semibold capitalize">
                  <span className="size-2.5 rounded-full" style={{ background: SEV_COLOR[sev] }} /> {sev} <span className="font-normal text-faint">{col.length}</span>
                </div>
                <div className="space-y-2.5">
                  {col.map((b, i) => (
                    <motion.div key={b.id} initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: i * 0.03 }}>
                      <Link to={b.id}>
                        <Card className="overflow-hidden transition hover:border-primary/50 hover:shadow-[var(--glow)]">
                          {b.annotated_screenshot && <img loading="lazy" src={fileUrl(slug, runId, b.annotated_screenshot)} alt="" className="aspect-[16/9] w-full border-b border-line object-cover object-top" />}
                          <div className="p-3">
                            <div className="flex items-center justify-between font-mono text-[11px] text-faint">{b.id}<Badge tone={STATUS_TONE[b.status]}>{STATUS_LABEL[b.status]}</Badge></div>
                            <div className="mt-1 text-[13.5px] font-medium leading-snug">{b.title}</div>
                            <div className="mt-2 flex flex-wrap gap-1 text-[11px]"><Badge>{b.module}</Badge><Badge tone="info">{b.category.replace("_", " ")}</Badge>{b.reproducibility && <Badge><Repeat /> {b.reproducibility}</Badge>}</div>
                          </div>
                        </Card>
                      </Link>
                    </motion.div>
                  ))}
                </div>
              </div>
            );
          })}
        </div>
      )}
      {list.length > 0 && view === "table" && (
        <Card className="overflow-hidden">
          <table className="w-full text-sm">
            <thead className="bg-primary-soft/30 text-left text-xs uppercase tracking-wide text-faint"><tr><th className="px-4 py-2.5">ID</th><th>Title</th><th>Severity</th><th>Priority</th><th>Module</th><th>Repro</th><th>Confidence</th><th className="px-4">Status</th></tr></thead>
            <tbody>{list.map((b) => (
              <tr key={b.id} className="border-t border-line hover:bg-primary-soft/30">
                <td className="px-4 py-2.5 font-mono text-xs"><Link to={b.id} className="text-blue-400 hover:underline">{b.id}</Link></td>
                <td className="py-2.5 pr-3"><Link to={b.id} className="font-medium hover:underline">{b.title}</Link></td>
                <td><Badge tone={severityTone(b.severity)}>{b.severity}</Badge></td><td>{b.priority}</td><td className="text-muted">{b.module}</td>
                <td className="font-mono text-xs">{b.reproducibility}</td><td>{pct(b.confidence)}</td><td className="px-4"><Badge tone={STATUS_TONE[b.status]}>{STATUS_LABEL[b.status]}</Badge></td>
              </tr>))}</tbody>
          </table>
        </Card>
      )}
    </>
  );
}

export function BugDetail() {
  const { slug = "", runId = "", bugId = "" } = useParams();
  const qc = useQueryClient();
  const bugs = useBugs(slug, runId);
  const bug = bugs.data?.bugs.find((b) => b.id === bugId);
  const update = useMutation({
    mutationFn: (status: BugStatus) => api.updateBug(slug, runId, bugId, { status }),
    onSuccess: (b) => { toast.success(`${b.id} marked ${STATUS_LABEL[b.status].toLowerCase()}`); qc.invalidateQueries({ queryKey: ["bugs", slug, runId] }); },
    onError: (e: Error) => toast.error(e.message),
  });
  const replay = useMutation({ mutationFn: () => api.replayBug(slug, runId, bugId), onSuccess: (r) => toast.info(r.message), onError: (e: Error) => toast.error(e.message) });
  const pdf = useMutation({
    mutationFn: () => api.createExport(slug, runId, "bug_pdf", bugId),
    onSuccess: (r) => window.open(fileUrl(slug, runId, r.files[0]), "_blank"),
    onError: (e: Error) => toast.error(e.message),
  });
  const crumbs = [{ label: "Projects", to: "/" }, { label: slug, to: `/projects/${slug}` }, { label: runId, to: `/projects/${slug}/runs/${runId}` }, { label: "Bugs", to: `/projects/${slug}/runs/${runId}/bugs` }];

  if (bugs.isLoading) return <Skeleton className="h-96 rounded-card" />;
  if (!bug) return <EmptyState icon={BugIcon} title="Bug not found" action={<Button asChild><Link to={`/projects/${slug}/runs/${runId}/bugs`}><ArrowLeft /> All bugs</Link></Button>} />;

  return (
    <>
      <PageHeader crumbs={crumbs}
        title={<span className="flex items-start gap-3"><span className="mt-1 font-mono text-base text-faint">{bug.id}</span>{bug.title}</span>}
        description={<span className="flex flex-wrap items-center gap-2">
          <Badge tone={severityTone(bug.severity)}><AlertOctagon /> {bug.severity}</Badge><Badge>{bug.priority}</Badge>
          <Badge tone={STATUS_TONE[bug.status]}>{STATUS_LABEL[bug.status]}</Badge><Badge><Repeat /> reproduced {bug.reproducibility}</Badge>
          <Badge>confidence {pct(bug.confidence)}</Badge>{bug.source === "automatic_check" && <Badge tone="info">automatic check</Badge>}
        </span>}
        actions={<>
          <Button variant="secondary" onClick={() => replay.mutate()} disabled={replay.isPending}><Play /> Replay in browser</Button>
          <Button variant="secondary" onClick={() => pdf.mutate()} disabled={pdf.isPending}>{pdf.isPending ? <Loader2 className="animate-spin" /> : <FileDown />} PDF</Button>
          {bug.status !== "confirmed" && <Button onClick={() => update.mutate("confirmed")}><Check /> Confirm</Button>}
          {bug.status !== "fixed" && <Button variant="secondary" onClick={() => update.mutate("fixed")}><Wrench /> Mark fixed</Button>}
          {bug.status !== "rejected" && <Button variant="ghost" onClick={() => update.mutate("rejected")}><X /> Not a bug</Button>}
          {bug.status === "rejected" && <Button variant="ghost" onClick={() => update.mutate("new")}><CheckCheck /> Reopen</Button>}
        </>} />

      <div className="grid gap-4 xl:grid-cols-[1.35fr_1fr]">
        <div className="space-y-4">
          {bug.annotated_screenshot && (
            <Card className="overflow-hidden"><a href={fileUrl(slug, runId, bug.annotated_screenshot)} target="_blank" rel="noreferrer">
              <img src={fileUrl(slug, runId, bug.annotated_screenshot)} alt={`Annotated screenshot of ${bug.id}`} className="w-full" /></a></Card>
          )}
          <div className="grid gap-4 md:grid-cols-2">
            {bug.clip && <Card className="p-3"><div className="mb-2 flex items-center gap-2 text-xs uppercase tracking-wider text-faint"><Clapperboard className="size-3.5" /> Bug clip</div>
              <video controls className="w-full rounded-lg" src={fileUrl(slug, runId, bug.clip)}><track kind="captions" /></video></Card>}
            {bug.video && <Card className="p-3"><div className="mb-2 flex items-center gap-2 text-xs uppercase tracking-wider text-faint"><Film className="size-3.5" /> Full test video</div>
              <video controls preload="none" className="w-full rounded-lg" src={fileUrl(slug, runId, bug.video)}><track kind="captions" /></video></Card>}
          </div>
          {(bug.console.length > 0 || bug.network.length > 0) && (
            <Card><CardHeader><CardTitle className="flex items-center gap-2"><ScrollText className="size-4" /> Logs</CardTitle></CardHeader>
              <CardContent className="space-y-1">{[...bug.console, ...bug.network].map((l, i) => <div key={i} className="break-all font-mono text-[11.5px] text-amber-300">{l}</div>)}</CardContent></Card>
          )}
        </div>
        <div className="space-y-4">
          <Card><CardContent className="space-y-4 pt-5 text-sm">
            <p>{bug.summary}</p>
            <div className="grid gap-3 sm:grid-cols-2">
              <div className="rounded-xl border border-green-500/30 bg-green-500/5 p-3"><div className="mb-1 text-xs uppercase tracking-wider text-green-400">Expected</div>{bug.expected}</div>
              <div className="rounded-xl border border-red-500/30 bg-red-500/5 p-3"><div className="mb-1 text-xs uppercase tracking-wider text-red-400">Actual</div>{bug.actual}</div>
            </div>
            {bug.preconditions.length > 0 && <div><div className="mb-1 text-xs uppercase tracking-wider text-faint">Preconditions</div><ul className="list-disc pl-5 text-muted">{bug.preconditions.map((p, i) => <li key={i}>{p}</li>)}</ul></div>}
            <div><div className="mb-1 text-xs uppercase tracking-wider text-faint">Steps to reproduce</div>
              <ol className="list-decimal space-y-1 pl-5">{bug.steps_to_reproduce.map((s, i) => <li key={i}>{s}</li>)}</ol></div>
            <div className="rounded-xl bg-slate-500/10 p-3 text-xs text-muted"><ShieldAlert className="mr-1 inline size-3.5" /> <b className="text-fg">Severity reasoning:</b> {bug.severity_reason}</div>
          </CardContent></Card>
          <Card><CardHeader><CardTitle className="flex items-center gap-2"><Monitor className="size-4" /> Environment</CardTitle></CardHeader>
            <CardContent><dl className="grid grid-cols-[110px_1fr] gap-x-3 gap-y-1.5 text-sm">
              {Object.entries({ Module: bug.module, Category: bug.category.replace("_", " "), Role: bug.environment.role, URL: bug.environment.url, Browser: bug.environment.browser, OS: bug.environment.os, Viewport: bug.environment.viewport, "Date / time": bug.environment.date_time }).map(([k, v]) => (
                <div key={k} className="contents"><dt className="text-faint">{k}</dt><dd className="break-all">{v || "—"}</dd></div>))}
            </dl></CardContent></Card>
          <Card><CardHeader><CardTitle className="flex items-center gap-2"><Eye className="size-4" /> Traceability</CardTitle></CardHeader>
            <CardContent className="space-y-2 text-sm">
              {bug.test_case_ids.length > 0 && <div>Test cases: {bug.test_case_ids.map((t) => <Link key={t} to={`/projects/${slug}/runs/${runId}/results`} className="mr-2 font-mono text-xs text-blue-400 hover:underline">{t}</Link>)}</div>}
              {Object.entries(bug.links).filter(([k]) => k !== "test_cases").map(([k, v]) => <div key={k} className="text-muted">{k}: <span className="font-mono text-xs">{v.join(", ")}</span></div>)}
            </CardContent></Card>
        </div>
      </div>
    </>
  );
}
