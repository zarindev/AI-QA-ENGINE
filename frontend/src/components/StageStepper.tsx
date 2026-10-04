import { motion } from "framer-motion";
import { Check, Compass, Brain, Network, FileText, ListChecks, Play, ShieldCheck, FileBarChart, X, Loader2, Minus } from "lucide-react";
import type { Run } from "@/lib/api";
import { cn, duration } from "@/lib/utils";

export const STAGES = [
  { key: "explore", label: "Explore", icon: Compass },
  { key: "understand", label: "Understand", icon: Brain },
  { key: "model", label: "Site model", icon: Network },
  { key: "requirements", label: "Requirements", icon: FileText },
  { key: "design", label: "Test design", icon: ListChecks },
  { key: "execute", label: "Execute", icon: Play },
  { key: "verify", label: "Verify", icon: ShieldCheck },
  { key: "report", label: "Report", icon: FileBarChart },
];

export function StageStepper({ run }: { run: Run }) {
  return (
    <ol className="grid grid-cols-2 gap-2 sm:grid-cols-4 xl:grid-cols-8">
      {STAGES.map(({ key, label, icon: Icon }, i) => {
        const st = run.stages[key];
        const status = st?.status ?? "pending";
        const running = status === "running";
        return (
          <motion.li
            key={key}
            initial={{ opacity: 0, y: 6 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: i * 0.03 }}
            className={cn(
              "relative overflow-hidden rounded-xl border p-3",
              status === "done" && "border-green-500/30 bg-green-500/5",
              running && "border-primary/50 bg-primary-soft shadow-[var(--glow)]",
              status === "failed" && "border-red-500/40 bg-red-500/5",
              (status === "pending" || status === "skipped") && "border-line bg-panel",
            )}
          >
            <div className="flex items-center justify-between">
              <span className={cn("grid size-7 place-items-center rounded-lg", running ? "bg-primary text-white" : "bg-slate-500/15 text-muted", status === "done" && "bg-green-500/20 text-green-400")}>
                <Icon className="size-4" />
              </span>
              <span className="text-faint">
                {status === "done" && <Check className="size-4 text-green-400" />}
                {running && <Loader2 className="size-4 animate-spin text-blue-400" />}
                {status === "failed" && <X className="size-4 text-red-400" />}
                {status === "skipped" && <Minus className="size-4" />}
              </span>
            </div>
            <div className="mt-2 text-[13px] font-semibold">{label}</div>
            <div className="mt-0.5 line-clamp-2 min-h-[2.2em] text-[11.5px] leading-snug text-muted">
              {status === "skipped" ? "Coming in a later phase" : st?.message || (status === "pending" ? "Waiting" : "")}
            </div>
            {running && (
              <div className="absolute inset-x-0 bottom-0 h-0.5 bg-slate-500/20">
                <div className="h-full bg-primary transition-[width] duration-500" style={{ width: `${Math.round((st?.progress ?? 0) * 100)}%` }} />
              </div>
            )}
            {status === "done" && st?.started_at && <div className="mt-1 font-mono text-[10.5px] text-faint">{duration(st.started_at, st.finished_at)}</div>}
          </motion.li>
        );
      })}
    </ol>
  );
}
