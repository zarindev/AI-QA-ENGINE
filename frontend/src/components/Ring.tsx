import { cn } from "@/lib/utils";

/** Circular gauge for scores and confidence (0–100). */
export function Ring({ value, size = 64, stroke = 6, label, className }: { value: number | null; size?: number; stroke?: number; label?: string; className?: string }) {
  const r = (size - stroke) / 2;
  const c = 2 * Math.PI * r;
  const v = value == null ? 0 : Math.max(0, Math.min(100, value));
  const color = value == null ? "var(--faint)" : v >= 80 ? "var(--pass)" : v >= 55 ? "var(--warn)" : "var(--fail)";
  return (
    <div className={cn("relative inline-grid place-items-center", className)} style={{ width: size, height: size }}>
      <svg width={size} height={size} className="-rotate-90">
        <circle cx={size / 2} cy={size / 2} r={r} stroke="var(--border-strong)" strokeWidth={stroke} fill="none" />
        <circle
          cx={size / 2}
          cy={size / 2}
          r={r}
          stroke={color}
          strokeWidth={stroke}
          fill="none"
          strokeLinecap="round"
          strokeDasharray={c}
          strokeDashoffset={c - (c * v) / 100}
          style={{ transition: "stroke-dashoffset 0.8s ease" }}
        />
      </svg>
      <div className="absolute text-center leading-none">
        <div className="font-semibold" style={{ fontSize: size * 0.28 }}>{value == null ? "—" : Math.round(v)}</div>
        {label && <div className="mt-0.5 text-[9px] uppercase tracking-wider text-faint">{label}</div>}
      </div>
    </div>
  );
}
