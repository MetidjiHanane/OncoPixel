import React from "react";
import { Navigate, Route, Routes } from "react-router-dom";
import Layout from "./components/Layout";
import { Spinner, Toasts } from "./ui";
import { useApp } from "./state";
import AuthPage from "./pages/Auth";
import Welcome from "./pages/Welcome";
import Dashboard from "./pages/Dashboard";
import Patients from "./pages/Patients";
import PatientDetail from "./pages/PatientDetail";
import ImportPage from "./pages/Import";
import Studies from "./pages/Studies";
import StudyPage from "./pages/Study";
import StudyPreview from "./pages/StudyPreview";
import Compare from "./pages/Compare";
import Models from "./pages/Models";
import SettingsPage from "./pages/Settings";
import Activity from "./pages/Activity";
import Help from "./pages/Help";

export default function App() {
  const { loading, backendDown, auth, settings, t, refreshAuth } = useApp();
  let body: React.ReactNode;
  if (loading) body = <div className="auth"><Spinner /></div>;
  else if (backendDown)
    body = (
      <div className="auth"><div className="card auth-card">
        <h2>{t("backend.down.title")}</h2><p className="sub">{t("backend.down.text")}</p>
        <button className="btn primary" onClick={() => refreshAuth()}>{t("common.retry")}</button>
      </div></div>
    );
  else if (!auth?.authenticated) body = <AuthPage />;
  else if (settings && !settings.welcome_seen) body = <Welcome />;
  else
    body = (
      <Layout>
        <Routes>
          <Route path="/" element={<Dashboard />} />
          <Route path="/patients" element={<Patients />} />
          <Route path="/patients/:id" element={<PatientDetail />} />
          <Route path="/import" element={<ImportPage />} />
          <Route path="/studies" element={<Studies />} />
          <Route path="/studies/:id" element={<StudyPage />} />
          <Route path="/study-preview" element={<StudyPreview />} />
          <Route path="/compare" element={<Compare />} />
          <Route path="/models" element={<Models />} />
          <Route path="/settings" element={<SettingsPage />} />
          <Route path="/activity" element={<Activity />} />
          <Route path="/help" element={<Help />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </Layout>
    );
  return <>{body}<Toasts /></>;
}
