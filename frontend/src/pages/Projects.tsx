import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { motion } from "framer-motion";
import { FlaskConical, FolderPlus, Globe, Loader2, Plus } from "lucide-react";
import { api, type Project } from "@/lib/api";
import { DOMAIN_LABELS, timeAgo } from "@/lib/utils";
import { PageHeader } from "@/components/PageHeader";
import { Ring } from "@/components/Ring";
import { Badge, statusTone } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { EmptyState, ErrorState, LoadingGrid } from "@/components/ui/states";

export function Projects() {
  const projects = useQuery({ queryKey: ["projects"], queryFn: api.projects, refetchInterval: 5000 });
  return (
    <>
      <PageHeader
        title="Projects"
        description="Every website you test lives here, with its runs, findings and reports."
        actions={
          <Button asChild>
            <Link to="/projects/new"><Plus /> New project</Link>
          </Button>
        }
      />
      {projects.isLoading && <LoadingGrid />}
      {projects.error && <ErrorState error={projects.error} retry={() => projects.refetch()} />}
      {projects.data && projects.data.length === 0 && (
        <EmptyState
          icon={FolderPlus}
          title="No projects yet"
          description="Add the URL of a site you own or are authorized to test — or take QA Pilot for a spin on the bundled demo clinic."
          action={
            <div className="flex gap-2">
              <Button asChild><Link to="/projects/new"><Plus /> New project</Link></Button>
              <Button variant="secondary" asChild><Link to="/onboarding"><FlaskConical /> Try a demo app</Link></Button>
            </div>
          }
        />
      )}
      {projects.data && projects.data.length > 0 && (
        <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
          {projects.data.map((p, i) => (
            <motion.div key={p.slug} initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: i * 0.04 }}>
              <ProjectCard project={p} />
            </motion.div>
          ))}
        </div>
      )}
    </>
  );
}

function ProjectCard({ project: p }: { project: Project }) {
  const run = p.latest_run;
  return (
    <Link to={`/projects/${p.slug}`} className="group block">
      <Card className="h-full p-5 transition group-hover:border-primary/50 group-hover:shadow-[var(--glow)]">
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0">
            <div className="truncate text-[15px] font-semibold">{p.name}</div>
            <div className="mt-0.5 flex items-center gap-1 truncate font-mono text-xs text-faint"><Globe className="size-3 shrink-0" />{p.url}</div>
          </div>
          <Ring value={run?.quality_score ?? null} size={52} stroke={5} label="score" />
        </div>
        <div className="mt-4 flex flex-wrap gap-1.5">
          {run?.domain ? <Badge tone="primary">{DOMAIN_LABELS[run.domain] ?? run.domain}</Badge> : <Badge>Not analysed</Badge>}
          <Badge tone={p.environment === "production" ? "warn" : "info"}>{p.environment}</Badge>
          <Badge>{p.roles.length} role{p.roles.length === 1 ? "" : "s"}</Badge>
        </div>
        <div className="mt-5 grid grid-cols-3 gap-2 border-t border-line pt-4 text-center">
          <Stat label="Pages" value={run?.pages ?? "—"} />
          <Stat label="Findings" value={run?.findings ?? "—"} />
          <Stat label="Open bugs" value={run?.bugs ?? "—"} />
        </div>
        <div className="mt-4 flex items-center justify-between text-xs text-muted">
          {run ? (
            <>
              <Badge tone={statusTone(run.status)}>{p.running && <Loader2 className="animate-spin" />}{run.status}</Badge>
              <span>Last run {timeAgo(run.started_at)}</span>
            </>
          ) : (
            <span>No runs yet</span>
          )}
        </div>
      </Card>
    </Link>
  );
}

function Stat({ label, value }: { label: string; value: number | string }) {
  return (
    <div>
      <div className="text-lg font-semibold">{value}</div>
      <div className="text-[11px] uppercase tracking-wide text-faint">{label}</div>
    </div>
  );
}
