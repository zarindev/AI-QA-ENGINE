import { useEffect, useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import {
  Ban, Check, CheckCheck, Coins, FileDown, FileSpreadsheet, ListChecks, Loader2, MessageSquarePlus, Play, Plus, RefreshCw,
  Save, Search, ShieldAlert, ShieldCheck, Timer, Trash2, X,
} from "lucide-react";
import * as DialogPrimitive from "@radix-ui/react-dialog";
import { api, fileUrl, type TestCase } from "@/lib/api";
import { PageHeader } from "@/components/PageHeader";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Dialog, DialogContent, DialogDescription, DialogTitle } from "@/components/ui/dialog";
import { Hint, Input, Label } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { EmptyState, ErrorState } from "@/components/ui/states";

const PRIORITY_TONE = { P1: "fail", P2: "warn", P3: "info", P4: "neutral" } as const;
const STATUS_TONE = { approved: "pass", draft: "warn", skipped: "neutral" } as const;
const TECHNIQUES = ["smoke", "crud", "e2e", "validation", "boundary", "equivalence", "negative", "state_transition", "permission",
  "data_integrity", "business_rule", "ui_responsive", "accessibility"];

export function TestCases() {
  const { slug = "", runId = "" } = useParams();
  const qc = useQueryClient();
  const suite = useQuery({ queryKey: ["testcases", slug, runId], queryFn: () => api.testcases(slug, runId), retry: false });
  const run = useQuery({ queryKey: ["run", slug, runId], queryFn: () => api.run(slug, runId), refetchInterval: (q) => (q.state.data?.running ? 2000 : false) });
  const est = useQuery({ queryKey: ["estimate", slug, runId], queryFn: () => api.estimate(slug, runId), enabled: !!suite.data });
  const exports = useQuery({ queryKey: ["exports", slug, runId], queryFn: () => api.exports(slug, runId) });
  const [q, setQ] = useState("");
  const [technique, setTechnique] = useState("all");
  const [priority, setPriority] = useState("all");
  const [status, setStatus] = useState("all");
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [open, setOpen] = useState<TestCase | null>(null);
  const [addOpen, setAddOpen] = useState(false);
  const regenerating = !!run.data?.running;

  const refresh = () => {
    qc.invalidateQueries({ queryKey: ["testcases", slug, runId] });
    qc.invalidateQueries({ queryKey: ["estimate", slug, runId] });
  };
  useEffect(() => { if (!regenerating) refresh(); }, [regenerating]); // eslint-disable-line react-hooks/exhaustive-deps

  const bulk = useMutation({
    mutationFn: (s: TestCase["status"]) => api.bulkCases(slug, runId, [...selected], s),
    onSuccess: (r, s) => { toast.success(`${r.updated} test cases ${s === "approved" ? "approved" : s === "skipped" ? "skipped" : "reset"}`); setSelected(new Set()); refresh(); },
    onError: (e: Error) => toast.error(e.message),
  });
  const regen = useMutation({
    mutationFn: () => api.regenerate(slug, runId),
    onSuccess: () => { toast.info("Regenerating — approved, edited and hand-written cases are kept"); run.refetch(); },
    onError: (e: Error) => toast.error(e.message),
  });
  const exp = useMutation({
    mutationFn: (kind: "testcases_xlsx" | "gherkin_zip") => api.createExport(slug, runId, kind),
    onSuccess: (r) => { qc.invalidateQueries({ queryKey: ["exports", slug, runId] }); window.open(fileUrl(slug, runId, r.files[0]), "_blank"); },
    onError: (e: Error) => toast.error(e.message),
  });

  const cases = useMemo(() => suite.data?.cases ?? [], [suite.data]);
  const filtered = useMemo(() => cases.filter((c) =>
    (technique === "all" || c.technique === technique) && (priority === "all" || c.priority === priority) &&
    (status === "all" || c.status === status) &&
    (!q || `${c.id} ${c.title} ${c.module} ${c.role}`.toLowerCase().includes(q.toLowerCase()))), [cases, technique, priority, status, q]);
  const modules = useMemo(() => [...new Set(filtered.map((c) => c.module))], [filtered]);
  const counts = { approved: cases.filter((c) => c.status === "approved").length, draft: cases.filter((c) => c.status === "draft").length, skipped: cases.filter((c) => c.status === "skipped").length };
  const crumbs = [{ label: "Projects", to: "/" }, { label: slug, to: `/projects/${slug}` }, { label: runId, to: `/projects/${slug}/runs/${runId}` }];

  if (suite.isLoading) return <Skeleton className="h-96 rounded-card" />;
  if (suite.error)
    return (<><PageHeader crumbs={crumbs} title="Test cases" />
      {(suite.error as { status?: number }).status === 404 ? <EmptyState icon={ListChecks} title="No test cases yet" description="They are designed after the requirements." /> : <ErrorState error={suite.error} retry={() => suite.refetch()} />}</>);
  const xlsx = exports.data?.find((e) => e.kind === "testcases_xlsx");

  return (
    <>
      <PageHeader
        crumbs={crumbs}
        title="Test cases"
        description={<>Review, edit and approve. Only <b>approved</b> cases run. {counts.approved} approved · {counts.draft} to review · {counts.skipped} skipped.</>}
        actions={
          <>
            <Button variant="ghost" asChild><Link to={`/projects/${slug}/runs/${runId}/requirements`}>Requirements</Link></Button>
            <Button variant="secondary" onClick={() => regen.mutate()} disabled={regenerating || regen.isPending}>
              {regenerating ? <Loader2 className="animate-spin" /> : <RefreshCw />} {regenerating ? "Regenerating…" : "Regenerate"}
            </Button>
            <Button variant="secondary" onClick={() => setAddOpen(true)}><MessageSquarePlus /> Add test</Button>
          </>
        }
      />

      <div className="mb-5 grid gap-3 lg:grid-cols-[1fr_auto]">
        <Card className="flex flex-wrap items-center gap-x-6 gap-y-2 px-5 py-4">
          <div className="text-xs uppercase tracking-wider text-faint">Estimate for {est.data?.cases ?? counts.approved} approved cases</div>
          {est.data ? (
            <>
              <span className="flex items-center gap-1.5 text-sm"><Coins className="size-4 text-amber-400" /> ≈ ${est.data.cost_usd.toFixed(2)}</span>
              <span className="flex items-center gap-1.5 text-sm"><Timer className="size-4 text-blue-400" /> ≈ {est.data.minutes} min</span>
              <span className="text-sm text-muted">{est.data.steps} steps · {est.data.model}</span>
              {est.data.blocked_in_safe_mode > 0 && <Badge tone="warn"><ShieldAlert /> {est.data.blocked_in_safe_mode} need Full Mode</Badge>}
            </>
          ) : <Skeleton className="h-5 w-56" />}
        </Card>
        <div className="flex flex-wrap items-center gap-2">
          <Button variant="secondary" onClick={() => exp.mutate("testcases_xlsx")} disabled={exp.isPending}><FileSpreadsheet /> Excel</Button>
          <Button variant="secondary" onClick={() => exp.mutate("gherkin_zip")} disabled={exp.isPending || counts.approved === 0}><FileDown /> Gherkin</Button>
          <Button disabled title="Test execution arrives in Phase 4"><Play /> Run approved tests</Button>
        </div>
      </div>
      {xlsx && <p className="-mt-3 mb-4 text-xs text-faint">Last Excel export: <a className="text-blue-400 hover:underline" href={fileUrl(slug, runId, xlsx.path)}>{xlsx.path}</a></p>}

      <div className="mb-3 flex flex-wrap items-center gap-2">
        <div className="relative w-64">
          <Search className="absolute left-3 top-1/2 size-4 -translate-y-1/2 text-faint" />
          <Input aria-label="Search test cases" placeholder="Search…" className="pl-9" value={q} onChange={(e) => setQ(e.target.value)} />
        </div>
        <Select label="Technique" value={technique} onChange={setTechnique} options={["all", ...TECHNIQUES]} />
        <Select label="Priority" value={priority} onChange={setPriority} options={["all", "P1", "P2", "P3", "P4"]} />
        <Select label="Status" value={status} onChange={setStatus} options={["all", "draft", "approved", "skipped"]} />
        <div className="ml-auto flex items-center gap-2">
          {selected.size > 0 && <span className="text-sm text-muted">{selected.size} selected</span>}
          <Button size="sm" variant="secondary" onClick={() => setSelected(new Set(filtered.map((c) => c.id)))}>Select all shown</Button>
          <Button size="sm" onClick={() => bulk.mutate("approved")} disabled={selected.size === 0 || bulk.isPending}><CheckCheck /> Approve</Button>
          <Button size="sm" variant="ghost" onClick={() => bulk.mutate("skipped")} disabled={selected.size === 0 || bulk.isPending}><Ban /> Skip</Button>
        </div>
      </div>

      {filtered.length === 0 && <EmptyState icon={ListChecks} title="No test cases match" description="Change the filters or add a test in plain English." />}
      <div className="space-y-4">
        {modules.map((m) => {
          const rows = filtered.filter((c) => c.module === m);
          return (
            <Card key={m} className="overflow-hidden">
              <div className="flex items-center justify-between border-b border-line bg-primary-soft/30 px-4 py-2.5">
                <div className="font-semibold">{m} <span className="ml-1 text-xs font-normal text-faint">{rows.length}</span></div>
                <button className="text-xs text-blue-400 hover:underline" onClick={() => setSelected(new Set([...selected, ...rows.map((r) => r.id)]))}>select module</button>
              </div>
              <table className="w-full text-sm">
                <tbody>
                  {rows.map((c) => (
                    <tr key={c.id} className="cursor-pointer border-t border-line first:border-t-0 hover:bg-primary-soft/30" onClick={() => setOpen(c)}>
                      <td className="w-10 px-4 py-2.5" onClick={(e) => e.stopPropagation()}>
                        <input type="checkbox" aria-label={`Select ${c.id}`} className="accent-blue-600" checked={selected.has(c.id)}
                          onChange={(e) => { const s = new Set(selected); if (e.target.checked) s.add(c.id); else s.delete(c.id); setSelected(s); }} />
                      </td>
                      <td className="w-32 font-mono text-xs text-faint">{c.id}</td>
                      <td className="py-2.5 pr-3"><div className="font-medium">{c.title}</div>
                        <div className="text-xs text-faint">{c.role || "any role"}{c.source === "ai" && " · designed by Claude"}{c.source === "plain_english" && " · from plain English"}{c.edited && " · edited"}</div></td>
                      <td className="w-36"><Badge tone="primary">{c.technique.replace("_", " ")}</Badge></td>
                      <td className="w-14"><Badge tone={PRIORITY_TONE[c.priority]}>{c.priority}</Badge></td>
                      <td className="w-10" title={c.requires_full_mode ? "Needs Full Mode (changes data)" : "Runs in Safe Mode"}>
                        {c.requires_full_mode ? <ShieldAlert className="size-4 text-amber-400" /> : <ShieldCheck className="size-4 text-green-400" />}</td>
                      <td className="w-28 pr-4 text-right"><Badge tone={STATUS_TONE[c.status]}>{c.status}</Badge></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </Card>
          );
        })}
      </div>
      {open && <CaseEditor key={open.id} slug={slug} runId={runId} c={open} onClose={() => setOpen(null)} onSaved={refresh} />}
      <AddDialog slug={slug} runId={runId} open={addOpen} onOpenChange={setAddOpen} onAdded={refresh} />
    </>
  );
}

function Select({ label, value, onChange, options }: { label: string; value: string; onChange: (v: string) => void; options: string[] }) {
  return (
    <select aria-label={label} value={value} onChange={(e) => onChange(e.target.value)} className="h-10 rounded-[10px] border border-line-strong bg-elevated px-3 text-sm">
      {options.map((o) => <option key={o} value={o}>{o === "all" ? `${label}: all` : o.replace("_", " ")}</option>)}
    </select>
  );
}

function CaseEditor({ slug, runId, c, onClose, onSaved }: { slug: string; runId: string; c: TestCase; onClose: () => void; onSaved: () => void }) {
  const [title, setTitle] = useState(c.title);
  const [priority, setPriority] = useState(c.priority);
  const [role, setRole] = useState(c.role);
  const [expected, setExpected] = useState(c.expected_result);
  const [steps, setSteps] = useState(c.steps.map((s) => ({ action: s.action, data: s.data, expected: s.expected })));
  const [full, setFull] = useState(c.requires_full_mode);
  const save = useMutation({
    mutationFn: (status?: TestCase["status"]) => api.updateCase(slug, runId, c.id, {
      title, priority, role, expected_result: expected, steps, requires_full_mode: full, ...(status ? { status } : {}),
    }),
    onSuccess: (_, s) => { toast.success(s === "approved" ? `${c.id} approved` : s === "skipped" ? `${c.id} skipped` : "Saved"); onSaved(); onClose(); },
    onError: (e: Error) => toast.error(e.message),
  });
  const setStatus = useMutation({
    mutationFn: (status: TestCase["status"]) => api.updateCase(slug, runId, c.id, { status }),
    onSuccess: () => { onSaved(); onClose(); },
    onError: (e: Error) => toast.error(e.message),
  });
  const del = useMutation({ mutationFn: () => api.deleteCase(slug, runId, c.id), onSuccess: () => { toast.success("Deleted"); onSaved(); onClose(); } });
  const dirty = title !== c.title || priority !== c.priority || role !== c.role || expected !== c.expected_result || full !== c.requires_full_mode ||
    JSON.stringify(steps) !== JSON.stringify(c.steps.map((s) => ({ action: s.action, data: s.data, expected: s.expected })));

  return (
    <DialogPrimitive.Root open onOpenChange={(o) => !o && onClose()}>
      <DialogPrimitive.Portal>
        <DialogPrimitive.Overlay className="fixed inset-0 z-40 bg-black/50" />
        <DialogPrimitive.Content className="fixed inset-y-0 right-0 z-50 flex w-[min(720px,96vw)] flex-col border-l border-line-strong bg-panel-solid shadow-2xl">
          <div className="flex items-start justify-between gap-3 border-b border-line p-5">
            <div>
              <div className="flex items-center gap-2 font-mono text-xs text-faint">{c.id} <Badge tone="primary">{c.technique.replace("_", " ")}</Badge> <Badge tone={STATUS_TONE[c.status]}>{c.status}</Badge></div>
              <DialogPrimitive.Title className="mt-1.5 text-lg font-semibold">{c.title}</DialogPrimitive.Title>
              <DialogPrimitive.Description className="text-xs text-muted">{c.module} · {Object.entries(c.links).filter(([k]) => k !== "pages").map(([k, v]) => `${k}: ${v.join(", ")}`).join(" · ") || "no linked requirements"}</DialogPrimitive.Description>
            </div>
            <DialogPrimitive.Close className="rounded-md p-1 text-muted hover:text-fg" aria-label="Close"><X className="size-5" /></DialogPrimitive.Close>
          </div>
          <div className="scrollbar-thin flex-1 space-y-4 overflow-y-auto p-5">
            <div><Label htmlFor="t-title">Title</Label><Input id="t-title" value={title} onChange={(e) => setTitle(e.target.value)} /></div>
            <div className="grid grid-cols-3 gap-3">
              <div><Label htmlFor="t-pri">Priority</Label>
                <select id="t-pri" value={priority} onChange={(e) => setPriority(e.target.value as TestCase["priority"])} className="h-10 w-full rounded-[10px] border border-line-strong bg-elevated px-3 text-sm">
                  {["P1", "P2", "P3", "P4"].map((p) => <option key={p}>{p}</option>)}</select></div>
              <div><Label htmlFor="t-role">Role</Label><Input id="t-role" value={role} onChange={(e) => setRole(e.target.value)} /></div>
              <label className="mt-6 flex items-center gap-2 text-sm"><input type="checkbox" className="accent-amber-500" checked={full} onChange={(e) => setFull(e.target.checked)} /> Needs Full Mode</label>
            </div>
            {c.preconditions.length > 0 && (
              <div><div className="mb-1 text-[13px] font-medium">Preconditions</div>
                <ul className="space-y-1 pl-5 text-sm text-muted">{c.preconditions.map((p, i) => <li key={i} className="list-disc">{p}</li>)}</ul></div>
            )}
            <div>
              <div className="mb-2 flex items-center justify-between"><span className="text-[13px] font-medium">Steps</span>
                <Button size="sm" variant="ghost" onClick={() => setSteps([...steps, { action: "", data: "", expected: "" }])}><Plus /> Step</Button></div>
              <div className="space-y-2">
                {steps.map((s, i) => (
                  <div key={i} className="grid grid-cols-[24px_1fr_auto] gap-2 rounded-lg border border-line p-2">
                    <span className="mt-2 text-center text-xs text-faint">{i + 1}</span>
                    <div className="space-y-1.5">
                      <Input aria-label={`Step ${i + 1} action`} placeholder="Action" value={s.action} onChange={(e) => setSteps(steps.map((x, j) => (j === i ? { ...x, action: e.target.value } : x)))} />
                      <div className="grid grid-cols-2 gap-1.5">
                        <Input aria-label={`Step ${i + 1} data`} placeholder="Data" className="font-mono text-xs" value={s.data} onChange={(e) => setSteps(steps.map((x, j) => (j === i ? { ...x, data: e.target.value } : x)))} />
                        <Input aria-label={`Step ${i + 1} expected`} placeholder="Expected" value={s.expected} onChange={(e) => setSteps(steps.map((x, j) => (j === i ? { ...x, expected: e.target.value } : x)))} />
                      </div>
                    </div>
                    <Button size="icon" variant="ghost" aria-label={`Remove step ${i + 1}`} onClick={() => setSteps(steps.filter((_, j) => j !== i))}><Trash2 /></Button>
                  </div>
                ))}
              </div>
            </div>
            <div><Label htmlFor="t-exp">Expected result</Label>
              <textarea id="t-exp" rows={3} value={expected} onChange={(e) => setExpected(e.target.value)} className="w-full rounded-[10px] border border-line-strong bg-elevated p-3 text-sm focus:border-primary focus:outline-none" /></div>
            {Object.keys(c.test_data).length > 0 && (
              <details><summary className="cursor-pointer text-[13px] font-medium">Test data</summary>
                <pre className="mt-2 overflow-x-auto rounded-lg bg-slate-500/10 p-3 font-mono text-[11px] text-muted">{JSON.stringify(c.test_data, null, 2)}</pre></details>
            )}
          </div>
          <div className="flex items-center gap-2 border-t border-line p-4">
            <Button variant="ghost" onClick={() => del.mutate()} aria-label="Delete test case"><Trash2 /></Button>
            <div className="ml-auto flex gap-2">
              {dirty && <Button variant="secondary" onClick={() => save.mutate(undefined)} disabled={save.isPending}><Save /> Save</Button>}
              <Button variant="ghost" onClick={() => (dirty ? save.mutate("skipped") : setStatus.mutate("skipped"))}><Ban /> Skip</Button>
              <Button onClick={() => (dirty ? save.mutate("approved") : setStatus.mutate("approved"))}><Check /> {dirty ? "Save & approve" : "Approve"}</Button>
            </div>
          </div>
        </DialogPrimitive.Content>
      </DialogPrimitive.Portal>
    </DialogPrimitive.Root>
  );
}

function AddDialog({ slug, runId, open, onOpenChange, onAdded }: { slug: string; runId: string; open: boolean; onOpenChange: (o: boolean) => void; onAdded: () => void }) {
  const [text, setText] = useState("");
  const add = useMutation({
    mutationFn: () => api.plainEnglish(slug, runId, text),
    onSuccess: (c) => { toast.success(`${c.id} added: ${c.title}`); setText(""); onOpenChange(false); onAdded(); },
    onError: (e: Error) => toast.error(e.message),
  });
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogTitle>Add a test in plain English</DialogTitle>
        <DialogDescription>Describe what to check. Claude turns it into steps, data and expected results you can edit.</DialogDescription>
        <textarea autoFocus rows={4} value={text} onChange={(e) => setText(e.target.value)} aria-label="Test description"
          placeholder="Test that a receptionist cannot delete a doctor"
          className="mt-4 w-full rounded-[10px] border border-line-strong bg-elevated p-3 text-sm focus:border-primary focus:outline-none" />
        <Hint>Examples: “A cancelled appointment cannot be invoiced” · “Booking a car for 7 days gives the weekly discount”</Hint>
        <div className="mt-5 flex justify-end gap-2">
          <Button variant="ghost" onClick={() => onOpenChange(false)}>Cancel</Button>
          <Button onClick={() => add.mutate()} disabled={text.trim().length < 8 || add.isPending}>{add.isPending ? <Loader2 className="animate-spin" /> : <MessageSquarePlus />} Create test</Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}
