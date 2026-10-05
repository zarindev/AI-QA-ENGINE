import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { Bot, CheckCircle2, Monitor, FolderOpen, Globe, KeyRound, Loader2, Save, ShieldCheck, XCircle } from "lucide-react";
import { api } from "@/lib/api";
import { PageHeader } from "@/components/PageHeader";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Hint, Input, Label } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { ErrorState } from "@/components/ui/states";

type Settings = Record<string, Record<string, unknown>>;

export function SettingsPage() {
  const qc = useQueryClient();
  const health = useQuery({ queryKey: ["health"], queryFn: api.health });
  const settings = useQuery({ queryKey: ["settings"], queryFn: api.settings });
  const [draft, setDraft] = useState<Settings | null>(null);
  useEffect(() => { if (settings.data) setDraft(structuredClone(settings.data)); }, [settings.data]);

  const save = useMutation({
    mutationFn: () => api.saveSettings({ ai: draft!.ai, browser: draft!.browser, crawl: draft!.crawl, safety: draft!.safety }),
    onSuccess: (data) => { toast.success("Settings saved to workspace/settings.json"); qc.setQueryData(["settings"], data); },
    onError: (e: Error) => toast.error(e.message),
  });
  const openFolder = useMutation({ mutationFn: api.openWorkspace, onError: (e: Error) => toast.error(e.message) });

  if (settings.isLoading || !draft) return settings.error ? <ErrorState error={settings.error} /> : <Skeleton className="h-96 rounded-card" />;
  const set = (section: string, key: string, value: unknown) => setDraft({ ...draft, [section]: { ...draft[section], [key]: value } });
  const num = (section: string, key: string) => Number(draft[section][key] ?? 0);

  return (
    <div className="max-w-4xl">
      <PageHeader title="Settings" description="Defaults live in config/settings.yaml; your changes are saved in workspace/settings.json."
        actions={<Button onClick={() => save.mutate()} disabled={save.isPending}>{save.isPending ? <Loader2 className="animate-spin" /> : <Save />} Save changes</Button>} />
      <div className="space-y-4">
        <Card>
          <CardHeader><div><CardTitle className="flex items-center gap-2"><Bot className="size-4" /> Claude</CardTitle><CardDescription>The only external service QA Pilot calls.</CardDescription></div></CardHeader>
          <CardContent className="space-y-4">
            <div className="flex items-center justify-between rounded-lg border border-line px-3 py-2.5 text-sm">
              <span className="flex items-center gap-2"><KeyRound className="size-4 text-faint" /> API key</span>
              {health.data?.api_key ? <span className="flex items-center gap-1 text-green-400"><CheckCircle2 className="size-4" /> {health.data.api_key_hint}</span>
                : <Link to="/onboarding" className="text-amber-400 hover:underline">Not set — add it</Link>}
            </div>
            <div className="grid gap-4 sm:grid-cols-3">
              <div><Label htmlFor="model">Model</Label><Input id="model" value={String(draft.ai.model)} onChange={(e) => set("ai", "model", e.target.value)} /></div>
              <div>
                <Label htmlFor="effort">Effort</Label>
                <select id="effort" value={String(draft.ai.effort)} onChange={(e) => set("ai", "effort", e.target.value)} className="h-10 w-full rounded-[10px] border border-line-strong bg-elevated px-3 text-sm">
                  {["low", "medium", "high", "xhigh", "max"].map((v) => <option key={v}>{v}</option>)}
                </select>
              </div>
              <div><Label htmlFor="budget">Cost budget per run ($)</Label><Input id="budget" type="number" step="1" value={num("ai", "run_cost_budget_usd")} onChange={(e) => set("ai", "run_cost_budget_usd", Number(e.target.value))} /><Hint>A run stops cleanly when it reaches this.</Hint></div>
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardHeader><div><CardTitle className="flex items-center gap-2"><Monitor className="size-4" /> Browser & crawling</CardTitle></div>
            {health.data && (health.data.chrome ? <span className="flex items-center gap-1 text-sm text-green-400"><CheckCircle2 className="size-4" /> Chrome found</span> : <span className="flex items-center gap-1 text-sm text-red-400"><XCircle className="size-4" /> Chrome not found</span>)}
          </CardHeader>
          <CardContent className="grid gap-4 sm:grid-cols-3">
            <label className="flex items-center gap-2 text-sm sm:col-span-3"><input type="checkbox" className="accent-blue-600" checked={Boolean(draft.browser.headless)} onChange={(e) => set("browser", "headless", e.target.checked)} /> Run Chrome in the background (headless)</label>
            <div><Label htmlFor="pages">Default max pages</Label><Input id="pages" type="number" value={num("crawl", "max_pages")} onChange={(e) => set("crawl", "max_pages", Number(e.target.value))} /></div>
            <div><Label htmlFor="depth">Default max depth</Label><Input id="depth" type="number" value={num("crawl", "max_depth")} onChange={(e) => set("crawl", "max_depth", Number(e.target.value))} /></div>
            <div><Label htmlFor="rate">Delay between pages (s)</Label><Input id="rate" type="number" step="0.1" value={num("crawl", "rate_limit_s")} onChange={(e) => set("crawl", "rate_limit_s", Number(e.target.value))} /><Hint>Be polite to the server.</Hint></div>
          </CardContent>
        </Card>

        <Card>
          <CardHeader><div><CardTitle className="flex items-center gap-2"><ShieldCheck className="size-4" /> Safe Mode deny-list</CardTitle><CardDescription>Elements, links and forms whose text matches one of these words are never clicked in Safe Mode.</CardDescription></div></CardHeader>
          <CardContent>
            <textarea aria-label="Safe Mode deny-list" rows={6} value={(draft.safety.deny_list as string[]).join("\n")}
              onChange={(e) => set("safety", "deny_list", e.target.value.split("\n").map((s) => s.trim()).filter(Boolean))}
              className="w-full rounded-[10px] border border-line-strong bg-elevated p-3 font-mono text-xs focus:border-primary focus:outline-none" />
          </CardContent>
        </Card>

        <Card>
          <CardHeader><div><CardTitle className="flex items-center gap-2"><Globe className="size-4" /> Workspace</CardTitle><CardDescription>All projects, runs, screenshots and reports — plain files you can zip, move or inspect.</CardDescription></div></CardHeader>
          <CardContent className="flex flex-wrap items-center gap-3">
            <code className="flex-1 truncate rounded-lg border border-line bg-elevated px-3 py-2 font-mono text-xs">{health.data?.workspace}</code>
            <Button variant="secondary" onClick={() => openFolder.mutate()}><FolderOpen /> Open folder</Button>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
