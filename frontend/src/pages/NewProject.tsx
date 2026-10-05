import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { AnimatePresence, motion } from "framer-motion";
import { toast } from "sonner";
import {
  ArrowLeft, ArrowRight, Check, Globe, KeyRound, Loader2, Plus, Server, ShieldAlert, ShieldCheck, SlidersHorizontal, Trash2, Users,
} from "lucide-react";
import { api } from "@/lib/api";
import { cn } from "@/lib/utils";
import { PageHeader } from "@/components/PageHeader";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Hint, Input, Label } from "@/components/ui/input";

type Env = "production" | "staging" | "test";
interface RoleRow { name: string; login_strategy: "credentials" | "manual_session"; username: string; password: string; login_url: string }

const STEPS = [
  { title: "Website", icon: Globe },
  { title: "Environment", icon: Server },
  { title: "Authorization", icon: ShieldCheck },
  { title: "Roles", icon: Users },
  { title: "Scope", icon: SlidersHorizontal },
  { title: "Mode", icon: ShieldAlert },
];

export function NewProject() {
  const navigate = useNavigate();
  const qc = useQueryClient();
  const [step, setStep] = useState(0);
  const [url, setUrl] = useState("");
  const [name, setName] = useState("");
  const [env, setEnv] = useState<Env>("production");
  const [authorized, setAuthorized] = useState(false);
  const [authorizedBy, setAuthorizedBy] = useState("");
  const [roles, setRoles] = useState<RoleRow[]>([]);
  const [maxPages, setMaxPages] = useState(40);
  const [maxDepth, setMaxDepth] = useState(4);
  const [exclude, setExclude] = useState("");
  const [mode, setMode] = useState<"safe" | "full">("safe");
  const [confirmFull, setConfirmFull] = useState(false);

  const create = useMutation({
    mutationFn: async () => {
      const project = await api.createProject({
        name, url, environment: env, authorized, authorized_by: authorizedBy,
        roles: roles.map((r) => ({ ...r, name: r.name.trim().toLowerCase() })),
        max_pages: maxPages, max_depth: maxDepth,
        exclude_patterns: exclude.split("\n").map((s) => s.trim()).filter(Boolean),
      });
      if (roles.some((r) => r.login_strategy === "manual_session")) return { project, run: null };
      const run = await api.startRun(project.slug, { mode, confirm_full_mode: confirmFull });
      return { project, run };
    },
    onSuccess: ({ project, run }) => {
      qc.invalidateQueries({ queryKey: ["projects"] });
      if (run) {
        toast.success("Project created — exploration started");
        navigate(`/projects/${project.slug}/runs/${run.id}`);
      } else {
        toast.info("Project created. Capture the manual logins, then start the first run.");
        navigate(`/projects/${project.slug}`);
      }
    },
    onError: (e: Error) => toast.error(e.message),
  });

  const validUrl = /^(https?:\/\/)?[\w.-]+\.[a-z]{2,}|^(https?:\/\/)?(localhost|127\.0\.0\.1)(:\d+)?/i.test(url.trim());
  const rolesValid = roles.every((r) => r.name.trim() && (r.login_strategy === "manual_session" || (r.username && r.password)));
  const canNext = [
    validUrl,
    true,
    authorized && authorizedBy.trim().length > 0,
    rolesValid,
    maxPages > 0,
    mode === "safe" || confirmFull,
  ][step];
  const fullAllowed = env !== "production";

  return (
    <div className="mx-auto max-w-3xl">
      <PageHeader title="New project" description="Six quick steps. Nothing is sent anywhere except your own Claude API calls." crumbs={[{ label: "Projects", to: "/" }]} />
      <ol className="mb-6 grid grid-cols-6 gap-2">
        {STEPS.map(({ title, icon: Icon }, i) => (
          <li key={title} className="flex flex-col items-center gap-1.5 text-center">
            <span className={cn("grid size-9 place-items-center rounded-xl border transition",
              i < step ? "border-green-500/40 bg-green-500/15 text-green-400" : i === step ? "border-primary bg-primary text-white" : "border-line text-faint")}>
              {i < step ? <Check className="size-4" /> : <Icon className="size-4" />}
            </span>
            <span className={cn("text-[11.5px]", i === step ? "text-fg" : "text-faint")}>{title}</span>
          </li>
        ))}
      </ol>

      <Card>
        <CardContent className="min-h-[300px] pt-6">
          <AnimatePresence mode="wait">
            <motion.div key={step} initial={{ opacity: 0, x: 12 }} animate={{ opacity: 1, x: 0 }} exit={{ opacity: 0, x: -12 }} transition={{ duration: 0.18 }}>
              {step === 0 && (
                <div className="space-y-5">
                  <div>
                    <Label htmlFor="url">Website URL</Label>
                    <Input id="url" autoFocus placeholder="https://app.example.com or http://localhost:8101" value={url} onChange={(e) => setUrl(e.target.value)} />
                    <Hint>The page QA Pilot starts from — usually the home or login page.</Hint>
                  </div>
                  <div>
                    <Label htmlFor="name">Project name <span className="text-faint">(optional)</span></Label>
                    <Input id="name" placeholder="Acme Clinic" value={name} onChange={(e) => setName(e.target.value)} />
                  </div>
                </div>
              )}
              {step === 1 && (
                <div>
                  <Label>Which environment is this?</Label>
                  <div className="mt-2 grid gap-3 sm:grid-cols-3">
                    {([
                      ["production", "Live site with real users and data. Safe Mode only."],
                      ["staging", "Pre-release copy. Full Mode allowed."],
                      ["test", "Throw-away test data. Full Mode allowed."],
                    ] as const).map(([value, help]) => (
                      <button key={value} type="button" onClick={() => { setEnv(value); if (value === "production") setMode("safe"); }}
                        className={cn("rounded-xl border p-4 text-left transition", env === value ? "border-primary bg-primary-soft" : "border-line hover:border-line-strong")}>
                        <div className="font-semibold capitalize">{value}</div>
                        <div className="mt-1 text-xs text-muted">{help}</div>
                      </button>
                    ))}
                  </div>
                </div>
              )}
              {step === 2 && (
                <div className="space-y-5">
                  <div className="rounded-xl border border-amber-500/30 bg-amber-500/10 p-4 text-sm text-amber-200">
                    Only test websites you own or have written permission to test. QA Pilot records who confirmed this and when.
                  </div>
                  <label className="flex cursor-pointer items-start gap-3 rounded-xl border border-line p-4">
                    <input type="checkbox" className="mt-1 size-4 accent-blue-600" checked={authorized} onChange={(e) => setAuthorized(e.target.checked)} />
                    <span>
                      <span className="font-medium">I own this website or am authorized to test it.</span>
                      <span className="mt-0.5 block text-xs text-muted">{url || "(no URL yet)"}</span>
                    </span>
                  </label>
                  <div>
                    <Label htmlFor="who">Your name</Label>
                    <Input id="who" placeholder="Your name" value={authorizedBy} onChange={(e) => setAuthorizedBy(e.target.value)} />
                  </div>
                </div>
              )}
              {step === 3 && (
                <div className="space-y-3">
                  <p className="text-sm text-muted">
                    Add one login per user type (admin, doctor, customer…). Credentials are encrypted on disk and never appear in logs or reports.
                    Use <b>manual login</b> for 2FA or single sign-on — you log in yourself in a Chrome window and QA Pilot keeps the session.
                  </p>
                  {roles.map((r, i) => (
                    <div key={i} className="rounded-xl border border-line p-4">
                      <div className="grid gap-3 sm:grid-cols-[1fr_auto]">
                        <div>
                          <Label htmlFor={`role-${i}`}>Role name</Label>
                          <Input id={`role-${i}`} placeholder="admin" value={r.name} onChange={(e) => setRoles(roles.map((x, j) => (j === i ? { ...x, name: e.target.value } : x)))} />
                        </div>
                        <div className="flex items-end gap-2">
                          {(["credentials", "manual_session"] as const).map((s) => (
                            <Button key={s} type="button" size="sm" variant={r.login_strategy === s ? "primary" : "secondary"}
                              onClick={() => setRoles(roles.map((x, j) => (j === i ? { ...x, login_strategy: s } : x)))}>
                              {s === "credentials" ? <KeyRound /> : <Users />} {s === "credentials" ? "Credentials" : "Manual login"}
                            </Button>
                          ))}
                          <Button type="button" size="icon" variant="ghost" aria-label="Remove role" onClick={() => setRoles(roles.filter((_, j) => j !== i))}><Trash2 /></Button>
                        </div>
                      </div>
                      {r.login_strategy === "credentials" && (
                        <div className="mt-3 grid gap-3 sm:grid-cols-2">
                          <div><Label htmlFor={`user-${i}`}>Username or email</Label><Input id={`user-${i}`} autoComplete="off" value={r.username} onChange={(e) => setRoles(roles.map((x, j) => (j === i ? { ...x, username: e.target.value } : x)))} /></div>
                          <div><Label htmlFor={`pass-${i}`}>Password</Label><Input id={`pass-${i}`} type="password" autoComplete="new-password" value={r.password} onChange={(e) => setRoles(roles.map((x, j) => (j === i ? { ...x, password: e.target.value } : x)))} /></div>
                        </div>
                      )}
                      <div className="mt-3"><Label htmlFor={`login-${i}`}>Login page URL <span className="text-faint">(optional)</span></Label><Input id={`login-${i}`} placeholder="Defaults to the start URL" value={r.login_url} onChange={(e) => setRoles(roles.map((x, j) => (j === i ? { ...x, login_url: e.target.value } : x)))} /></div>
                    </div>
                  ))}
                  <Button type="button" variant="outline" onClick={() => setRoles([...roles, { name: "", login_strategy: "credentials", username: "", password: "", login_url: "" }])}>
                    <Plus /> Add role
                  </Button>
                  {roles.length === 0 && <Hint>No roles: only public pages will be explored. That is fine for marketing sites.</Hint>}
                </div>
              )}
              {step === 4 && (
                <div className="space-y-5">
                  <div className="grid gap-4 sm:grid-cols-2">
                    <div><Label htmlFor="pages">Max pages per role</Label><Input id="pages" type="number" min={1} max={500} value={maxPages} onChange={(e) => setMaxPages(Number(e.target.value))} /></div>
                    <div><Label htmlFor="depth">Max link depth</Label><Input id="depth" type="number" min={0} max={10} value={maxDepth} onChange={(e) => setMaxDepth(Number(e.target.value))} /></div>
                  </div>
                  <div>
                    <Label htmlFor="exclude">Skip URLs matching <span className="text-faint">(one regular expression per line)</span></Label>
                    <textarea id="exclude" rows={4} value={exclude} onChange={(e) => setExclude(e.target.value)} placeholder={"/blog/\n/docs/"}
                      className="w-full rounded-[10px] border border-line-strong bg-elevated p-3 font-mono text-xs focus:border-primary focus:outline-none" />
                  </div>
                </div>
              )}
              {step === 5 && (
                <div className="space-y-3">
                  <button type="button" onClick={() => setMode("safe")} className={cn("w-full rounded-xl border p-4 text-left", mode === "safe" ? "border-primary bg-primary-soft" : "border-line")}>
                    <div className="flex items-center gap-2 font-semibold"><ShieldCheck className="size-4 text-green-400" /> Safe Mode <span className="text-xs font-normal text-faint">recommended</span></div>
                    <div className="mt-1 text-sm text-muted">Never clicks anything that looks like delete, pay, checkout, transfer or log out. Only search/filter forms are submitted.</div>
                  </button>
                  <button type="button" disabled={!fullAllowed} onClick={() => setMode("full")}
                    className={cn("w-full rounded-xl border p-4 text-left disabled:cursor-not-allowed disabled:opacity-50", mode === "full" ? "border-amber-500 bg-amber-500/10" : "border-line")}>
                    <div className="flex items-center gap-2 font-semibold"><ShieldAlert className="size-4 text-amber-400" /> Full Mode</div>
                    <div className="mt-1 text-sm text-muted">{fullAllowed ? "Creates, edits and deletes test records (prefixed QAP_) to test complete workflows." : "Only available for staging and test environments."}</div>
                  </button>
                  {mode === "full" && (
                    <label className="flex cursor-pointer items-start gap-3 rounded-xl border border-amber-500/40 bg-amber-500/10 p-4 text-sm">
                      <input type="checkbox" className="mt-0.5 size-4 accent-amber-500" checked={confirmFull} onChange={(e) => setConfirmFull(e.target.checked)} />
                      I understand Full Mode may change or delete data in this {env} environment.
                    </label>
                  )}
                </div>
              )}
            </motion.div>
          </AnimatePresence>
        </CardContent>
      </Card>

      <div className="mt-5 flex justify-between">
        <Button variant="ghost" onClick={() => setStep(step - 1)} disabled={step === 0}><ArrowLeft /> Back</Button>
        {step < STEPS.length - 1 ? (
          <Button onClick={() => setStep(step + 1)} disabled={!canNext}>Next <ArrowRight /></Button>
        ) : (
          <Button onClick={() => create.mutate()} disabled={!canNext || create.isPending}>
            {create.isPending ? <Loader2 className="animate-spin" /> : <Check />} Create & start
          </Button>
        )}
      </div>
    </div>
  );
}
