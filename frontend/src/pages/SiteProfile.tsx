import { Link, useParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { motion } from "framer-motion";
import { Boxes, Brain, CircleCheck, Database, Eye, Layers, Network, Sparkles, Users } from "lucide-react";
import { api } from "@/lib/api";
import { DOMAIN_LABELS } from "@/lib/utils";
import { PageHeader } from "@/components/PageHeader";
import { Ring } from "@/components/Ring";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { EmptyState, ErrorState } from "@/components/ui/states";

export function SiteProfile() {
  const { slug = "", runId = "" } = useParams();
  const profile = useQuery({ queryKey: ["profile", slug, runId], queryFn: () => api.profile(slug, runId), retry: false });
  const crumbs = [{ label: "Projects", to: "/" }, { label: slug, to: `/projects/${slug}` }, { label: runId, to: `/projects/${slug}/runs/${runId}` }];

  if (profile.isLoading) return <Skeleton className="h-96 rounded-card" />;
  if (profile.error)
    return (
      <>
        <PageHeader crumbs={crumbs} title="Site profile" />
        {(profile.error as { status?: number }).status === 404 ? (
          <EmptyState icon={Brain} title="Not analysed yet" description="The site profile appears once the Understand stage finishes." />
        ) : (
          <ErrorState error={profile.error} retry={() => profile.refetch()} />
        )}
      </>
    );
  const p = profile.data!;

  return (
    <>
      <PageHeader crumbs={crumbs} title="Site profile" description="What QA Pilot learned about this application — and why."
        actions={<Button variant="secondary" asChild><Link to={`/projects/${slug}/runs/${runId}/model`}><Network /> Knowledge graph</Link></Button>} />

      <motion.div initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }}>
        <Card className="mb-4 overflow-hidden">
          <div className="flex flex-wrap items-center gap-6 bg-gradient-to-r from-primary/15 via-transparent to-transparent p-6">
            <Ring value={p.confidence * 100} size={96} stroke={8} label="confidence" />
            <div className="min-w-0 flex-1">
              <div className="flex flex-wrap items-center gap-2">
                <h2 className="text-2xl font-semibold tracking-tight">{DOMAIN_LABELS[p.domain] ?? p.domain}</h2>
                {p.sub_type && <span className="text-lg text-muted">· {p.sub_type}</span>}
              </div>
              <p className="mt-2 max-w-3xl text-[15px] text-muted">{p.summary}</p>
              <div className="mt-3 flex flex-wrap gap-2">
                <Badge tone={p.method === "ai" ? "primary" : "warn"}>
                  <Sparkles /> {p.method === "ai" ? "Analysed by Claude" : "Offline keyword classifier"}
                </Badge>
                {p.domain_pack && <Badge tone="info"><Layers /> Domain pack: {p.domain_pack}</Badge>}
                <Badge><Users /> {p.roles.length} roles</Badge>
                <Badge><Database /> {p.entities.length} entities</Badge>
              </div>
            </div>
          </div>
        </Card>
      </motion.div>

      <div className="grid gap-4 lg:grid-cols-3">
        <Card className="lg:col-span-2">
          <CardHeader><div><CardTitle className="flex items-center gap-2"><Eye className="size-4" /> Evidence</CardTitle><CardDescription>The observations behind the verdict.</CardDescription></div></CardHeader>
          <CardContent>
            <ul className="space-y-2">
              {p.evidence.map((e, i) => (
                <li key={i} className="flex items-start gap-3 rounded-lg border border-line px-3 py-2.5">
                  <CircleCheck className="mt-0.5 size-4 shrink-0 text-green-400" />
                  <div className="min-w-0 flex-1">
                    <div className="text-sm">{e.claim}</div>
                    <div className="truncate font-mono text-[11px] text-faint">{e.source}</div>
                  </div>
                  <div className="w-16 shrink-0"><div className="h-1.5 rounded-full bg-slate-500/20"><div className="h-full rounded-full bg-primary" style={{ width: `${e.weight * 100}%` }} /></div></div>
                </li>
              ))}
            </ul>
            {Object.keys(p.domain_scores).length > 0 && (
              <div className="mt-5">
                <div className="mb-2 text-xs uppercase tracking-wider text-faint">Keyword scores</div>
                <div className="space-y-1.5">
                  {Object.entries(p.domain_scores).map(([d, s]) => {
                    const max = Math.max(...Object.values(p.domain_scores), 1);
                    return (
                      <div key={d} className="flex items-center gap-3 text-sm">
                        <span className="w-24 text-muted">{DOMAIN_LABELS[d] ?? d}</span>
                        <div className="h-2 flex-1 rounded-full bg-slate-500/15"><div className="h-full rounded-full bg-primary/70" style={{ width: `${(s / max) * 100}%` }} /></div>
                        <span className="w-10 text-right font-mono text-xs">{s}</span>
                      </div>
                    );
                  })}
                </div>
              </div>
            )}
          </CardContent>
        </Card>

        <div className="space-y-4">
          <Card>
            <CardHeader><CardTitle className="flex items-center gap-2"><Users className="size-4" /> Roles</CardTitle></CardHeader>
            <CardContent className="space-y-2">
              {p.role_details.map((r) => (
                <div key={r.name} className="rounded-lg border border-line px-3 py-2">
                  <div className="flex items-center justify-between"><span className="font-medium">{r.name}</span>{r.observed ? <Badge tone="pass">explored</Badge> : <Badge>inferred</Badge>}</div>
                  {r.description && <div className="mt-0.5 text-xs text-muted">{r.description}</div>}
                </div>
              ))}
            </CardContent>
          </Card>
          <Card>
            <CardHeader><CardTitle className="flex items-center gap-2"><Boxes className="size-4" /> Modules</CardTitle></CardHeader>
            <CardContent className="flex flex-wrap gap-1.5">
              {p.modules.map((m) => <Badge key={m} tone="primary">{m}</Badge>)}
            </CardContent>
          </Card>
        </div>
      </div>

      {p.features.length > 0 && (
        <Card className="mt-4">
          <CardHeader><CardTitle className="flex items-center gap-2"><Sparkles className="size-4" /> Feature inventory</CardTitle></CardHeader>
          <CardContent className="grid gap-2 sm:grid-cols-2 xl:grid-cols-3">
            {p.features.map((f) => (
              <div key={f.id} className="rounded-lg border border-line px-3 py-2.5">
                <div className="flex items-center justify-between gap-2"><span className="font-medium">{f.name}</span><span className="font-mono text-[10.5px] text-faint">{f.id}</span></div>
                {f.description && <div className="mt-0.5 text-xs text-muted">{f.description}</div>}
                <div className="mt-1.5 flex flex-wrap gap-1">{f.roles.map((r) => <Badge key={r}>{r}</Badge>)}</div>
              </div>
            ))}
          </CardContent>
        </Card>
      )}

      <h2 className="mb-3 mt-8 flex items-center gap-2 text-lg font-semibold"><Database className="size-5" /> Entities</h2>
      <div className="grid gap-4 lg:grid-cols-2">
        {p.entities.map((e) => (
          <Card key={e.name}>
            <CardHeader>
              <div><CardTitle>{e.name}</CardTitle><CardDescription className="font-mono">{e.pages.join("  ")}</CardDescription></div>
              <div className="flex flex-wrap justify-end gap-1">{e.operations.map((o) => <Badge key={o} tone="info">{o}</Badge>)}</div>
            </CardHeader>
            <CardContent>
              <table className="w-full text-sm">
                <thead className="text-left text-[11px] uppercase tracking-wide text-faint"><tr><th className="pb-1.5">Field</th><th className="pb-1.5">Type</th><th className="pb-1.5">Rules</th></tr></thead>
                <tbody>
                  {e.fields.map((f) => (
                    <tr key={f.name} className="border-t border-line">
                      <td className="py-1.5">{f.name}{f.required && <span className="ml-1 text-red-400" title="required">*</span>}</td>
                      <td className="py-1.5 font-mono text-xs text-muted">{f.type}</td>
                      <td className="py-1.5 text-xs text-muted">{f.validation || "—"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
              {e.relations.length > 0 && <div className="mt-3 text-xs text-muted">Related to: {e.relations.join(", ")}</div>}
            </CardContent>
          </Card>
        ))}
      </div>
    </>
  );
}
