import { Link, useParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { Check, ShieldAlert, ShieldCheck, X } from "lucide-react";
import { api, type MatrixCell } from "@/lib/api";
import { cn } from "@/lib/utils";
import { PageHeader } from "@/components/PageHeader";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { EmptyState, ErrorState } from "@/components/ui/states";

function Cell({ c }: { c: MatrixCell }) {
  const tip = `${c.role} → ${c.page}\nExpected: ${c.expected} (${c.source})\nObserved: ${c.observed}${c.evidence ? `\n${c.evidence}` : ""}`;
  if (c.hole)
    return <div title={tip} className="grid h-9 place-items-center rounded-md bg-red-500/30 text-red-300 ring-1 ring-red-500/60 light:text-red-800"><ShieldAlert className="size-4" /></div>;
  if (c.observed === "untested")
    return <div title={tip} className="grid h-9 place-items-center rounded-md border border-dashed border-line text-faint">?</div>;
  return (
    <div title={tip} className={cn("grid h-9 place-items-center rounded-md", c.observed === "allow" ? "bg-green-500/20 text-green-400" : "bg-slate-500/15 text-muted")}>
      {c.observed === "allow" ? <Check className="size-4" /> : <X className="size-4" />}
    </div>
  );
}

export function Permissions() {
  const { slug = "", runId = "" } = useParams();
  const m = useQuery({ queryKey: ["permissions", slug, runId], queryFn: () => api.permissions(slug, runId), retry: false });
  const crumbs = [{ label: "Projects", to: "/" }, { label: slug, to: `/projects/${slug}` }, { label: runId, to: `/projects/${slug}/runs/${runId}` }];
  if (m.isLoading) return <Skeleton className="h-96 rounded-card" />;
  if (m.error) return (<><PageHeader crumbs={crumbs} title="Permission matrix" /><ErrorState error={m.error} retry={() => m.refetch()} /></>);
  const v = m.data!;
  if (v.roles.length === 0)
    return (<><PageHeader crumbs={crumbs} title="Permission matrix" /><EmptyState icon={ShieldCheck} title="No signed-in roles" description="Add role credentials to the project to compare what each role can open." /></>);

  return (
    <>
      <PageHeader crumbs={crumbs} title="Permission matrix"
        description={<>Which role can open which screen. Expected access comes from each role's own menus; observed access from exploring and from direct-URL permission tests. {v.holes > 0 ? <b className="text-red-400">{v.holes} permission hole{v.holes > 1 ? "s" : ""}.</b> : "No holes found."}</>}
        actions={<Button variant="secondary" asChild><Link to={`/projects/${slug}/runs/${runId}/quality`}>Coverage & quality</Link></Button>} />
      <Card className="overflow-x-auto p-4">
        <table className="text-xs">
          <thead>
            <tr><th className="sticky left-0 bg-panel-solid px-2 py-1.5 text-left font-medium text-faint">Screen</th>
              {v.roles.map((r) => <th key={r} className="w-24 px-1 py-1.5 font-medium capitalize">{r}</th>)}</tr>
          </thead>
          <tbody>
            {v.pages.map((p) => (
              <tr key={p}>
                <td className="sticky left-0 max-w-[340px] truncate bg-panel-solid px-2 py-1 font-mono" title={p}>{p}</td>
                {v.roles.map((r) => { const c = v.cells.find((x) => x.role === r && x.page === p); return <td key={r} className="p-0.5">{c && <Cell c={c} />}</td>; })}
              </tr>
            ))}
          </tbody>
        </table>
        <div className="mt-4 flex flex-wrap gap-4 text-[11px] text-faint">
          <span className="flex items-center gap-1.5"><Check className="size-3.5 text-green-400" /> can open</span>
          <span className="flex items-center gap-1.5"><X className="size-3.5" /> denied</span>
          <span className="flex items-center gap-1.5"><ShieldAlert className="size-3.5 text-red-400" /> hole: opens but should not</span>
          <span className="flex items-center gap-1.5">? not tested</span>
          <Badge tone="info">hover a cell for evidence</Badge>
        </div>
      </Card>
    </>
  );
}
