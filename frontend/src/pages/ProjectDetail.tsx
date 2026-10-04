import { useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { Globe, History, KeyRound, Loader2, LogIn, Play, ShieldAlert, ShieldCheck, Trash2, UserCheck } from "lucide-react";
import { api, type Project } from "@/lib/api";
import { DOMAIN_LABELS, duration, timeAgo } from "@/lib/utils";
import { PageHeader } from "@/components/PageHeader";
import { Badge, statusTone } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Dialog, DialogContent, DialogDescription, DialogTitle } from "@/components/ui/dialog";
import { Skeleton } from "@/components/ui/skeleton";
import { EmptyState, ErrorState } from "@/components/ui/states";

export function ProjectDetail() {
  const { slug = "" } = useParams();
  const navigate = useNavigate();
  const qc = useQueryClient();
  const project = useQuery({ queryKey: ["project", slug], queryFn: () => api.project(slug) });
  const runs = useQuery({ queryKey: ["runs", slug], queryFn: () => api.runs(slug), refetchInterval: 4000 });
  const [startOpen, setStartOpen] = useState(false);
  const [deleteOpen, setDeleteOpen] = useState(false);

  const del = useMutation({
    mutationFn: () => api.deleteProject(slug),
    onSuccess: () => {
      toast.success("Project deleted");
      qc.invalidateQueries({ queryKey: ["projects"] });
      navigate("/");
    },
    onError: (e: Error) => toast.error(e.message),
  });

  if (project.isLoading) return <Skeleton className="h-64 rounded-card" />;
  if (project.error) return <ErrorState error={project.error} retry={() => project.refetch()} />;
  const p = project.data!;
  const running = runs.data?.some((r) => r.running);

  return (
    <>
      <PageHeader
        crumbs={[{ label: "Projects", to: "/" }]}
        title={p.name}
        description={<span className="flex items-center gap-1.5 font-mono text-xs"><Globe className="size-3.5" /><a href={p.url} target="_blank" rel="noreferrer" className="hover:text-fg">{p.url}</a></span>}
        actions={
          <>
            <Button variant="ghost" onClick={() => setDeleteOpen(true)}><Trash2 /> Delete</Button>
            <Button onClick={() => setStartOpen(true)} disabled={running}>{running ? <Loader2 className="animate-spin" /> : <Play />} {running ? "Run in progress" : "Start run"}</Button>
          </>
        }
      />

      <div className="grid gap-4 lg:grid-cols-3">
        <Card className="lg:col-span-2">
          <CardHeader>
            <div><CardTitle className="flex items-center gap-2"><History className="size-4" /> Runs</CardTitle><CardDescription>Each run is a folder of readable files in your workspace.</CardDescription></div>
          </CardHeader>
          <CardContent>
            {runs.isLoading && <Skeleton className="h-32" />}
            {runs.data && runs.data.length === 0 && (
              <EmptyState icon={Play} title="No runs yet" description="Start the first run to explore the site and work out what it does." action={<Button onClick={() => setStartOpen(true)}><Play /> Start run</Button>} />
            )}
            {runs.data && runs.data.length > 0 && (
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead className="text-left text-xs uppercase tracking-wide text-faint">
                    <tr><th className="pb-2 font-medium">Run</th><th className="pb-2 font-medium">Status</th><th className="pb-2 font-medium">Mode</th><th className="pb-2 font-medium">Domain</th><th className="pb-2 font-medium">Pages</th><th className="pb-2 font-medium">Findings</th><th className="pb-2 font-medium">Duration</th></tr>
                  </thead>
                  <tbody>
                    {runs.data.map((r) => (
                      <tr key={r.id} className="border-t border-line hover:bg-primary-soft/40">
                        <td className="py-2.5"><Link to={`/projects/${slug}/runs/${r.id}`} className="font-mono text-xs text-blue-400 hover:underline">{r.id}</Link><div className="text-xs text-faint">{timeAgo(r.started_at)}</div></td>
                        <td><Badge tone={statusTone(r.status)}>{r.running && <Loader2 className="animate-spin" />}{r.status}</Badge></td>
                        <td><Badge tone={r.mode === "full" ? "warn" : "pass"}>{r.mode}</Badge></td>
                        <td>{r.domain ? DOMAIN_LABELS[r.domain] ?? r.domain : "—"}</td>
                        <td>{r.pages || "—"}</td>
                        <td>{r.findings || "—"}</td>
                        <td className="font-mono text-xs text-muted">{duration(r.started_at, r.finished_at)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </CardContent>
        </Card>

        <div className="space-y-4">
          <Card>
            <CardHeader><CardTitle>Project</CardTitle></CardHeader>
            <CardContent className="space-y-2 text-sm">
              <Row label="Environment"><Badge tone={p.environment === "production" ? "warn" : "info"}>{p.environment}</Badge></Row>
              <Row label="Authorized by">{p.authorized_by}</Row>
              <Row label="Confirmed">{new Date(p.authorized_at).toLocaleString()}</Row>
              <Row label="Limits">{p.scope.max_pages} pages · depth {p.scope.max_depth}</Row>
            </CardContent>
          </Card>
          <RolesCard project={p} />
        </div>
      </div>

      <StartRunDialog project={p} open={startOpen} onOpenChange={setStartOpen} />
      <Dialog open={deleteOpen} onOpenChange={setDeleteOpen}>
        <DialogContent>
          <DialogTitle>Delete “{p.name}”?</DialogTitle>
          <DialogDescription>This removes the project folder with all runs, screenshots and encrypted credentials from your workspace. It cannot be undone.</DialogDescription>
          <div className="mt-6 flex justify-end gap-2">
            <Button variant="ghost" onClick={() => setDeleteOpen(false)}>Keep it</Button>
            <Button variant="danger" onClick={() => del.mutate()} disabled={del.isPending}>{del.isPending ? <Loader2 className="animate-spin" /> : <Trash2 />} Delete project</Button>
          </div>
        </DialogContent>
      </Dialog>
    </>
  );
}

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return <div className="flex items-center justify-between gap-3"><span className="text-muted">{label}</span><span className="text-right">{children}</span></div>;
}

function RolesCard({ project }: { project: Project }) {
  const [capturing, setCapturing] = useState<string | null>(null);
  const start = useMutation({
    mutationFn: (role: string) => api.startManualLogin(project.slug, role),
    onSuccess: (r, role) => { setCapturing(role); toast.info(r.message); },
    onError: (e: Error) => toast.error(e.message),
  });
  const finish = useMutation({
    mutationFn: (role: string) => api.finishManualLogin(project.slug, role),
    onSuccess: () => { setCapturing(null); toast.success("Session saved (encrypted)"); },
    onError: (e: Error) => { setCapturing(null); toast.error(e.message); },
  });
  return (
    <Card>
      <CardHeader><div><CardTitle>Roles</CardTitle><CardDescription>Explored separately, one browser each.</CardDescription></div></CardHeader>
      <CardContent className="space-y-2">
        {project.roles.length === 0 && <p className="text-sm text-muted">Public pages only.</p>}
        {project.roles.map((r) => (
          <div key={r.name} className="flex items-center justify-between rounded-lg border border-line px-3 py-2">
            <div className="flex items-center gap-2 text-sm">
              {r.login_strategy === "manual_session" ? <UserCheck className="size-4 text-faint" /> : <KeyRound className="size-4 text-faint" />}
              <span className="font-medium">{r.name}</span>
              <span className="text-xs text-faint">{r.login_strategy === "manual_session" ? "manual login" : "credentials"}</span>
            </div>
            {r.login_strategy === "manual_session" && (capturing === r.name ? (
              <Button size="sm" onClick={() => finish.mutate(r.name)} disabled={finish.isPending}>{finish.isPending ? <Loader2 className="animate-spin" /> : <UserCheck />} I'm logged in</Button>
            ) : (
              <Button size="sm" variant="secondary" onClick={() => start.mutate(r.name)} disabled={start.isPending}><LogIn /> Capture login</Button>
            ))}
          </div>
        ))}
      </CardContent>
    </Card>
  );
}

function StartRunDialog({ project, open, onOpenChange }: { project: Project; open: boolean; onOpenChange: (o: boolean) => void }) {
  const navigate = useNavigate();
  const qc = useQueryClient();
  const [mode, setMode] = useState<"safe" | "full">("safe");
  const [confirm, setConfirm] = useState(false);
  const fullAllowed = project.environment !== "production";
  const start = useMutation({
    mutationFn: () => api.startRun(project.slug, { mode, confirm_full_mode: confirm }),
    onSuccess: (run) => { qc.invalidateQueries({ queryKey: ["runs", project.slug] }); navigate(`/projects/${project.slug}/runs/${run.id}`); },
    onError: (e: Error) => toast.error(e.message),
  });
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogTitle>Start a run</DialogTitle>
        <DialogDescription>QA Pilot explores every role, works out what the app does and builds its site model.</DialogDescription>
        <div className="mt-5 space-y-2">
          <button onClick={() => setMode("safe")} className={`w-full rounded-xl border p-3 text-left ${mode === "safe" ? "border-primary bg-primary-soft" : "border-line"}`}>
            <div className="flex items-center gap-2 font-medium"><ShieldCheck className="size-4 text-green-400" /> Safe Mode</div>
            <div className="text-xs text-muted">Read-only exploration. Recommended.</div>
          </button>
          <button disabled={!fullAllowed} onClick={() => setMode("full")} className={`w-full rounded-xl border p-3 text-left disabled:opacity-50 ${mode === "full" ? "border-amber-500 bg-amber-500/10" : "border-line"}`}>
            <div className="flex items-center gap-2 font-medium"><ShieldAlert className="size-4 text-amber-400" /> Full Mode</div>
            <div className="text-xs text-muted">{fullAllowed ? "May create, change or delete test data." : "Only for staging/test projects."}</div>
          </button>
          {mode === "full" && (
            <label className="flex items-start gap-2 rounded-xl border border-amber-500/40 bg-amber-500/10 p-3 text-sm">
              <input type="checkbox" className="mt-0.5 accent-amber-500" checked={confirm} onChange={(e) => setConfirm(e.target.checked)} /> I understand data may be changed.
            </label>
          )}
        </div>
        <div className="mt-6 flex justify-end gap-2">
          <Button variant="ghost" onClick={() => onOpenChange(false)}>Cancel</Button>
          <Button onClick={() => start.mutate()} disabled={start.isPending || (mode === "full" && !confirm)}>{start.isPending ? <Loader2 className="animate-spin" /> : <Play />} Start</Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}
