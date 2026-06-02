import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";
import AppShell from "./layouts/AppShell";
import RequirementIntake from "./pages/product/RequirementIntake";
import AIAnalysisPreview from "./pages/product/AIAnalysisPreview";
import MySubmissions from "./pages/product/MySubmissions";
import Dashboard from "./pages/owner/Dashboard";
import TicketDetail from "./pages/owner/TicketDetail";
import Analysis from "./pages/owner/Analysis";
import Workspace from "./pages/owner/Workspace";
import FeatureRoadmap from "./pages/progress/FeatureRoadmap";
import Settings from "./pages/settings/Settings";

function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route element={<AppShell />}>
          {/* Default redirect */}
          <Route path="/" element={<Navigate to="/de/dashboard" replace />} />

          {/* Product */}
          <Route path="/product/intake" element={<RequirementIntake />} />
          <Route path="/product/analysis-preview" element={<AIAnalysisPreview />} />
          <Route path="/product/submissions" element={<MySubmissions />} />

          {/* Team dashboards */}
          <Route path="/:team/dashboard" element={<Dashboard />} />
          <Route path="/:team/ticket/:ticketId" element={<TicketDetail />} />
          <Route path="/:team/ticket/:ticketId/analyze" element={<Analysis />} />
          <Route path="/:team/ticket/:ticketId/workspace" element={<Workspace />} />

          {/* Progress */}
          <Route path="/progress" element={<FeatureRoadmap />} />

          {/* Settings */}
          <Route path="/settings" element={<Settings />} />
        </Route>
      </Routes>
    </BrowserRouter>
  );
}

export default App;
