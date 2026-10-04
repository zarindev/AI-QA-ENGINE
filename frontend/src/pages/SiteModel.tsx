import { useMemo, useState } from "react";
import { useParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { Background, Controls, Handle, MiniMap, Position, ReactFlow, type Node, type NodeProps } from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import { Boxes, Database, FileText, LayoutGrid, Network, Sparkles, User, X } from "lucide-react";
import { api, type FlowNode } from "@/lib/api";
import { cn } from "@/lib/utils";
import { PageHeader } from "@/components/PageHeader";
import { Badge } from "@/components/ui/badge";
import { Card } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { EmptyState, ErrorState } from "@/components/ui/states";

const KINDS = [
  { key: "role", label: "Roles", icon: User, color: "#a78bfa" },
  { key: "module", label: "Modules", icon: LayoutGrid, color: "#38bdf8" },
  { key: "feature", label: "Features", icon: Sparkles, color: "#f59e0b" },
  { key: "page", label: "Pages", icon: FileText, color: "#60a5fa" },
  { key: "entity", label: "Entities", icon: Database, color: "#34d399" },
  { key: "field", label: "Fields", icon: Boxes, color: "#94a3b8" },
] as const;
const COLOR: Record<string, string> = Object.fromEntries(KINDS.map((k) => [k.key, k.color]));
const ICON = Object.fromEntries(KINDS.map((k) => [k.key, k.icon]));

function GraphNode({ data, selected }: NodeProps<Node<FlowNode["data"]>>) {
  const kind = data.kind as string;
  const Icon = ICON[kind] ?? Network;
  return (
    <div className={cn("w-[220px] rounded-xl border bg-panel-solid px-3 py-2 shadow-lg transition", selected ? "ring-2 ring-primary" : "")} style={{ borderColor: `${COLOR[kind]}66` }}>
      <Handle type="target" position={Position.Left} className="!size-1.5 !border-0" style={{ background: COLOR[kind] }} />
      <div className="flex items-center gap-2">
        <span className="grid size-6 shrink-0 place-items-center rounded-md" style={{ background: `${COLOR[kind]}22`, color: COLOR[kind] }}><Icon className="size-3.5" /></span>
        <div className="min-w-0">
          <div className="truncate text-[12.5px] font-semibold text-fg">{String(data.label)}</div>
          <div className="truncate font-mono text-[10px] text-faint">
            {kind === "page" ? String(data.template ?? "") : kind === "entity" ? `${data.field_count ?? 0} fields` : kind}
          </div>
        </div>
      </div>
      <Handle type="source" position={Position.Right} className="!size-1.5 !border-0" style={{ background: COLOR[kind] }} />
    </div>
  );
}
const nodeTypes = Object.fromEntries(KINDS.map((k) => [k.key, GraphNode]));

export function SiteModel() {
  const { slug = "", runId = "" } = useParams();
  const [kinds, setKinds] = useState<string[]>(["role", "page", "entity"]);
  const [selected, setSelected] = useState<FlowNode | null>(null);
  const [showLinks, setShowLinks] = useState(false);
  const model = useQuery({ queryKey: ["model", slug, runId, kinds], queryFn: () => api.model(slug, runId, kinds), retry: false });
  const crumbs = [{ label: "Projects", to: "/" }, { label: slug, to: `/projects/${slug}` }, { label: runId, to: `/projects/${slug}/runs/${runId}` }];

  const edges = useMemo(
    () => (model.data?.edges ?? []).filter((e) => showLinks || e.label !== "links_to").map((e) => ({
      ...e, label: undefined, animated: e.label === "can_access" && kinds.length <= 3,
      style: { stroke: e.label === "relates_to" ? "#34d399" : e.label === "links_to" ? "rgba(96,165,250,0.35)" : "rgba(148,163,184,0.35)", strokeWidth: 1.2 },
    })),
    [model.data, kinds.length, showLinks],
  );

  return (
    <>
      <PageHeader crumbs={crumbs} title="Site knowledge graph" description="Roles, screens, records and how they connect — built from what QA Pilot saw." />
      <div className="mb-3 flex flex-wrap items-center gap-2">
        {KINDS.map(({ key, label, icon: Icon, color }) => {
          const on = kinds.includes(key);
          return (
            <button key={key} onClick={() => setKinds(on ? kinds.filter((k) => k !== key) : [...kinds, key])}
              className={cn("flex items-center gap-1.5 rounded-full border px-3 py-1 text-xs transition", on ? "text-fg" : "border-line text-faint")}
              style={on ? { borderColor: `${color}88`, background: `${color}1a` } : undefined} aria-pressed={on}>
              <Icon className="size-3.5" style={{ color }} /> {label}
              {model.data?.stats[key] != null && <span className="text-faint">{model.data.stats[key]}</span>}
            </button>
          );
        })}
        <label className="ml-auto flex items-center gap-2 text-xs text-muted">
          <input type="checkbox" className="accent-blue-600" checked={showLinks} onChange={(e) => setShowLinks(e.target.checked)} /> Show navigation links
        </label>
      </div>
      {model.isLoading && <Skeleton className="h-[640px] rounded-card" />}
      {model.error && ((model.error as { status?: number }).status === 404
        ? <EmptyState icon={Network} title="No site model yet" description="The graph is built after the Understand stage." />
        : <ErrorState error={model.error} retry={() => model.refetch()} />)}
      {model.data && (
        <Card className="relative h-[680px] overflow-hidden">
          <ReactFlow nodes={model.data.nodes as Node[]} edges={edges} nodeTypes={nodeTypes} fitView minZoom={0.15}
            onNodeClick={(_, n) => setSelected(n as unknown as FlowNode)} onPaneClick={() => setSelected(null)} proOptions={{ hideAttribution: true }}>
            <Background color="rgba(148,163,184,0.15)" gap={22} />
            <Controls showInteractive={false} />
            <MiniMap pannable zoomable bgColor="transparent" nodeColor={(n) => COLOR[String(n.type)] ?? "#64748b"} maskColor="rgba(10,15,28,0.55)" />
          </ReactFlow>
          {selected && <NodePanel node={selected} onClose={() => setSelected(null)} />}
        </Card>
      )}
    </>
  );
}

function NodePanel({ node, onClose }: { node: FlowNode; onClose: () => void }) {
  const d = node.data;
  const rows = Object.entries(d).filter(([k, v]) => !["label", "kind", "page_ids"].includes(k) && v !== null && v !== "" && !(Array.isArray(v) && v.length === 0));
  return (
    <div className="absolute right-3 top-3 z-10 w-80 rounded-xl border border-line-strong bg-panel-solid p-4 shadow-2xl">
      <div className="flex items-start justify-between gap-2">
        <div><Badge style={{ background: `${COLOR[d.kind]}22`, color: COLOR[d.kind] }}>{d.kind}</Badge><div className="mt-1.5 font-semibold">{d.label}</div></div>
        <button onClick={onClose} className="rounded p-1 text-muted hover:text-fg" aria-label="Close details"><X className="size-4" /></button>
      </div>
      <dl className="mt-3 space-y-1.5 text-xs">
        {rows.map(([k, v]) => (
          <div key={k} className="grid grid-cols-[90px_1fr] gap-2">
            <dt className="text-faint">{k.replace(/_/g, " ")}</dt>
            <dd className="break-words font-mono text-muted">{Array.isArray(v) ? v.join(", ") : typeof v === "object" ? JSON.stringify(v) : String(v)}</dd>
          </div>
        ))}
      </dl>
    </div>
  );
}
