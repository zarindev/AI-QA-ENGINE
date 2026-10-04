import { useEffect, useState } from "react";
import { Link, NavLink, Outlet, useNavigate } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { Command } from "cmdk";
import { FolderKanban, KeyRound, Moon, Plus, Search, Settings, Sun, FlaskConical } from "lucide-react";
import { api } from "@/lib/api";
import { cn } from "@/lib/utils";
import { useTheme } from "@/hooks/useTheme";
import { Dialog, DialogContent, DialogTitle } from "@/components/ui/dialog";

const NAV = [
  { to: "/", label: "Projects", icon: FolderKanban, end: true },
  { to: "/projects/new", label: "New project", icon: Plus },
  { to: "/settings", label: "Settings", icon: Settings },
];

export function AppShell() {
  const { theme, toggle } = useTheme();
  const [paletteOpen, setPaletteOpen] = useState(false);
  const health = useQuery({ queryKey: ["health"], queryFn: api.health });

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        setPaletteOpen((o) => !o);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  return (
    <div className="flex h-full">
      <aside className="hidden w-60 shrink-0 flex-col border-r border-line bg-elevated/60 px-3 py-5 backdrop-blur md:flex">
        <Link to="/" className="mb-7 flex items-center gap-2.5 px-2">
          <img src="/logo.svg" alt="" className="size-8 rounded-lg shadow-[0_0_24px_rgba(37,99,235,0.5)]" />
          <div>
            <div className="text-[15px] font-semibold tracking-tight">QA Pilot</div>
            <div className="text-[11px] text-faint">AI website QA · local</div>
          </div>
        </Link>
        <nav className="space-y-1">
          {NAV.map(({ to, label, icon: Icon, end }) => (
            <NavLink
              key={to}
              to={to}
              end={end}
              className={({ isActive }) =>
                cn(
                  "flex items-center gap-2.5 rounded-lg px-2.5 py-2 text-[13.5px] font-medium text-muted transition hover:bg-primary-soft hover:text-fg",
                  isActive && "bg-primary-soft text-fg",
                )
              }
            >
              <Icon className="size-4" /> {label}
            </NavLink>
          ))}
        </nav>
        <button
          onClick={() => setPaletteOpen(true)}
          className="mt-6 flex items-center gap-2 rounded-lg border border-line px-2.5 py-2 text-left text-[13px] text-faint hover:border-line-strong hover:text-muted"
        >
          <Search className="size-4" /> Search…
          <kbd className="ml-auto rounded border border-line px-1.5 font-mono text-[10px]">Ctrl K</kbd>
        </button>
        <div className="mt-auto space-y-3 px-1">
          {health.data && !health.data.api_key && (
            <Link to="/onboarding" className="flex items-start gap-2 rounded-lg border border-amber-500/30 bg-amber-500/10 p-2.5 text-xs text-amber-300">
              <KeyRound className="mt-0.5 size-3.5 shrink-0" /> Add your Anthropic API key to unlock AI analysis.
            </Link>
          )}
          <div className="flex items-center justify-between text-xs text-faint">
            <span className="font-mono">v{health.data?.version ?? "…"}</span>
            <button onClick={toggle} className="rounded-md p-1.5 hover:bg-primary-soft hover:text-fg" aria-label="Toggle light/dark theme">
              {theme === "dark" ? <Sun className="size-4" /> : <Moon className="size-4" />}
            </button>
          </div>
        </div>
      </aside>
      <main className="scrollbar-thin flex-1 overflow-y-auto">
        <div className="mx-auto max-w-[1400px] px-6 py-7 lg:px-10">
          <Outlet />
        </div>
      </main>
      <CommandPalette open={paletteOpen} onOpenChange={setPaletteOpen} toggleTheme={toggle} />
    </div>
  );
}

function CommandPalette({ open, onOpenChange, toggleTheme }: { open: boolean; onOpenChange: (o: boolean) => void; toggleTheme: () => void }) {
  const navigate = useNavigate();
  const projects = useQuery({ queryKey: ["projects"], queryFn: api.projects, enabled: open });
  const go = (to: string) => {
    onOpenChange(false);
    navigate(to);
  };
  const item = "flex cursor-pointer items-center gap-2 rounded-lg px-3 py-2 text-sm text-muted data-[selected=true]:bg-primary-soft data-[selected=true]:text-fg";
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="top-[20%] translate-y-0 p-0">
        <DialogTitle className="sr-only">Command palette</DialogTitle>
        <Command label="Command palette" className="overflow-hidden rounded-2xl">
          <Command.Input placeholder="Jump to a project or action…" className="w-full border-b border-line bg-transparent px-4 py-3.5 text-sm outline-none placeholder:text-faint" />
          <Command.List className="max-h-80 overflow-y-auto p-2">
            <Command.Empty className="px-3 py-6 text-center text-sm text-faint">No results.</Command.Empty>
            <Command.Group heading="Actions" className="text-xs text-faint [&_[cmdk-group-heading]]:px-3 [&_[cmdk-group-heading]]:py-1.5">
              <Command.Item className={item} onSelect={() => go("/projects/new")}>
                <Plus className="size-4" /> New project
              </Command.Item>
              <Command.Item className={item} onSelect={() => go("/onboarding")}>
                <FlaskConical className="size-4" /> Try with a demo app
              </Command.Item>
              <Command.Item className={item} onSelect={() => go("/settings")}>
                <Settings className="size-4" /> Settings
              </Command.Item>
              <Command.Item className={item} onSelect={() => { toggleTheme(); onOpenChange(false); }}>
                <Sun className="size-4" /> Toggle light / dark
              </Command.Item>
            </Command.Group>
            {projects.data && projects.data.length > 0 && (
              <Command.Group heading="Projects" className="text-xs text-faint [&_[cmdk-group-heading]]:px-3 [&_[cmdk-group-heading]]:py-1.5">
                {projects.data.map((p) => (
                  <Command.Item key={p.slug} value={`${p.name} ${p.url}`} className={item} onSelect={() => go(`/projects/${p.slug}`)}>
                    <FolderKanban className="size-4" /> {p.name}
                    <span className="ml-auto truncate font-mono text-xs text-faint">{p.url}</span>
                  </Command.Item>
                ))}
              </Command.Group>
            )}
          </Command.List>
        </Command>
      </DialogContent>
    </Dialog>
  );
}
