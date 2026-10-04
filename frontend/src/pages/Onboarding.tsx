import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { motion } from "framer-motion";
import { toast } from "sonner";
import { ArrowRight, CheckCircle2, Monitor, ExternalLink, FlaskConical, KeyRound, Loader2, Lock, XCircle } from "lucide-react";
import { api } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Hint, Input, Label } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";

export function Onboarding() {
  const qc = useQueryClient();
  const navigate = useNavigate();
  const health = useQuery({ queryKey: ["health"], queryFn: api.health });
  const [key, setKey] = useState("");
  const [workspace, setWorkspace] = useState("");
  const [needsWorkspace, setNeedsWorkspace] = useState(false);
  const save = useMutation({
    mutationFn: () => api.saveApiKey(key, workspace),
    onSuccess: () => {
      toast.success("API key validated and saved to .env");
      setKey("");
      qc.invalidateQueries({ queryKey: ["health"] });
    },
    onError: (e: Error) => {
      if (e.message.includes("workspace")) setNeedsWorkspace(true);
      toast.error(e.message);
    },
  });
  const demo = useMutation({
    mutationFn: api.startDemo,
    onSuccess: (r) => navigate(`/projects/${r.project}/runs/${r.run}`),
    onError: (e: Error) => toast.error(e.message),
  });

  return (
    <div className="mx-auto max-w-3xl py-6">
      <motion.div initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} className="mb-8 text-center">
        <img src="/logo.svg" alt="" className="mx-auto mb-5 size-16 rounded-2xl shadow-[0_0_60px_rgba(37,99,235,0.55)]" />
        <h1 className="text-3xl font-semibold tracking-tight">Welcome to QA Pilot</h1>
        <p className="mx-auto mt-2 max-w-xl text-muted">
          Give it a URL. It learns the app, writes the tests, runs them, and reports the bugs — all on your computer.
        </p>
      </motion.div>

      <div className="space-y-4">
        <Card>
          <CardContent className="pt-5">
            <div className="flex items-start gap-4">
              <div className="grid size-10 shrink-0 place-items-center rounded-xl bg-primary-soft text-primary"><KeyRound className="size-5" /></div>
              <div className="flex-1">
                <div className="flex items-center justify-between">
                  <h2 className="font-semibold">1 · Connect Claude</h2>
                  {health.isLoading ? <Skeleton className="h-5 w-20" /> : health.data?.api_key ? (
                    <span className="flex items-center gap-1 text-sm text-green-400"><CheckCircle2 className="size-4" /> Connected {health.data.api_key_hint}</span>
                  ) : (
                    <span className="text-sm text-amber-400">Not set</span>
                  )}
                </div>
                <p className="mt-1 text-sm text-muted">
                  QA Pilot uses your own Anthropic API key. It is stored only in the <code className="font-mono text-xs">.env</code> file next to the app and is
                  the only thing that leaves your machine.
                </p>
                <form className="mt-4 flex gap-2" onSubmit={(e) => { e.preventDefault(); save.mutate(); }}>
                  <div className="flex-1">
                    <Label htmlFor="api-key" className="sr-only">Anthropic API key</Label>
                    <Input id="api-key" type="password" autoComplete="off" placeholder="sk-ant-…" value={key} onChange={(e) => setKey(e.target.value)} />
                  </div>
                  <Button type="submit" disabled={!key || save.isPending}>
                    {save.isPending ? <Loader2 className="animate-spin" /> : <Lock />} Validate & save
                  </Button>
                </form>
                {needsWorkspace && (
                  <div className="mt-3">
                    <Label htmlFor="workspace-id">Workspace ID</Label>
                    <Input id="workspace-id" placeholder="wrkspc_…" value={workspace} onChange={(e) => setWorkspace(e.target.value)} />
                    <Hint>
                      Your key is not tied to a workspace. Find the ID in the Console under Settings → Workspaces, or create
                      a key inside a workspace instead.
                    </Hint>
                  </div>
                )}
                <Hint>
                  Get a key at{" "}
                  <a className="text-blue-400 hover:underline" href="https://console.anthropic.com/settings/keys" target="_blank" rel="noreferrer">
                    console.anthropic.com <ExternalLink className="inline size-3" />
                  </a>
                  . Without a key, exploration still works and sites are classified offline with lower confidence.
                </Hint>
              </div>
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardContent className="pt-5">
            <div className="flex items-start gap-4">
              <div className="grid size-10 shrink-0 place-items-center rounded-xl bg-primary-soft text-primary"><Monitor className="size-5" /></div>
              <div className="flex-1">
                <div className="flex items-center justify-between">
                  <h2 className="font-semibold">2 · Google Chrome</h2>
                  {health.isLoading ? <Skeleton className="h-5 w-20" /> : health.data?.chrome ? (
                    <span className="flex items-center gap-1 text-sm text-green-400"><CheckCircle2 className="size-4" /> Found</span>
                  ) : (
                    <span className="flex items-center gap-1 text-sm text-red-400"><XCircle className="size-4" /> Not found</span>
                  )}
                </div>
                <p className="mt-1 text-sm text-muted">
                  QA Pilot drives a real Chrome browser. The matching driver downloads automatically.
                  {health.data && !health.data.chrome && (
                    <> Install Chrome from <a className="text-blue-400 hover:underline" href="https://www.google.com/chrome/" target="_blank" rel="noreferrer">google.com/chrome</a>, then reload this page.</>
                  )}
                </p>
              </div>
            </div>
          </CardContent>
        </Card>

        <Card className="border-primary/40 shadow-[var(--glow)]">
          <CardContent className="pt-5">
            <div className="flex flex-wrap items-center gap-4">
              <div className="grid size-10 shrink-0 place-items-center rounded-xl bg-primary text-white"><FlaskConical className="size-5" /></div>
              <div className="min-w-0 flex-1">
                <h2 className="font-semibold">3 · Try it on a demo app</h2>
                <p className="mt-1 text-sm text-muted">Starts the bundled CarePoint Clinic app (with deliberately planted bugs) and runs QA Pilot against it.</p>
              </div>
              <Button size="lg" onClick={() => demo.mutate()} disabled={demo.isPending || health.data?.chrome === false}>
                {demo.isPending ? <Loader2 className="animate-spin" /> : <FlaskConical />} Try with a demo app
              </Button>
            </div>
          </CardContent>
        </Card>
      </div>

      <div className="mt-8 text-center">
        <Link to="/" className="inline-flex items-center gap-1 text-sm text-muted hover:text-fg">
          Continue to projects <ArrowRight className="size-4" />
        </Link>
      </div>
    </div>
  );
}
