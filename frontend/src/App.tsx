import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { AppShell } from "@/components/layout/AppShell";
import { Onboarding } from "@/pages/Onboarding";
import { Projects } from "@/pages/Projects";
import { NewProject } from "@/pages/NewProject";
import { ProjectDetail } from "@/pages/ProjectDetail";
import { RunOverview } from "@/pages/RunOverview";
import { SiteProfile } from "@/pages/SiteProfile";
import { SiteModel } from "@/pages/SiteModel";
import { SettingsPage } from "@/pages/Settings";
import { Requirements } from "@/pages/Requirements";
import { TestCases } from "@/pages/TestCases";
import { EmptyState } from "@/components/ui/states";
import { Compass } from "lucide-react";

function Home() {
  // First run: no API key and no projects -> onboarding.
  const health = useQuery({ queryKey: ["health"], queryFn: api.health });
  const projects = useQuery({ queryKey: ["projects"], queryFn: api.projects });
  if (health.data && projects.data && !health.data.api_key && projects.data.length === 0) return <Navigate to="/onboarding" replace />;
  return <Projects />;
}

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route element={<AppShell />}>
          <Route index element={<Home />} />
          <Route path="onboarding" element={<Onboarding />} />
          <Route path="projects/new" element={<NewProject />} />
          <Route path="projects/:slug" element={<ProjectDetail />} />
          <Route path="projects/:slug/runs/:runId" element={<RunOverview />} />
          <Route path="projects/:slug/runs/:runId/profile" element={<SiteProfile />} />
          <Route path="projects/:slug/runs/:runId/model" element={<SiteModel />} />
          <Route path="projects/:slug/runs/:runId/requirements" element={<Requirements />} />
          <Route path="projects/:slug/runs/:runId/tests" element={<TestCases />} />
          <Route path="settings" element={<SettingsPage />} />
          <Route path="*" element={<EmptyState icon={Compass} title="Page not found" description="That screen does not exist." />} />
        </Route>
      </Routes>
    </BrowserRouter>
  );
}
