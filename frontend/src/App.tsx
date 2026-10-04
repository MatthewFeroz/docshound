import { lazy, Suspense } from "react";
import { Navigate, Route, Routes } from "react-router-dom";

import { Loading } from "./components/Status";
import { HomePage } from "./pages/HomePage";

const DocumentPage = lazy(() =>
  import("./pages/DocumentPage").then((module) => ({
    default: module.DocumentPage,
  })),
);
const FindingPage = lazy(() =>
  import("./pages/FindingPage").then((module) => ({
    default: module.FindingPage,
  })),
);
const FindingsPage = lazy(() =>
  import("./pages/FindingsPage").then((module) => ({
    default: module.FindingsPage,
  })),
);
const UsagePage = lazy(() =>
  import("./pages/UsagePage").then((module) => ({ default: module.UsagePage })),
);
const PullRequestPage = lazy(() =>
  import("./pages/PullRequestPage").then((module) => ({
    default: module.PullRequestPage,
  })),
);

export default function App() {
  return (
    <Suspense fallback={<Loading label="Loading page…" />}>
      <Routes>
        <Route path="/" element={<HomePage />} />
        <Route
          path="/showcase"
          element={<Navigate to="/#overview" replace />}
        />
        <Route path="/usage" element={<UsagePage />} />
        <Route path="/findings" element={<FindingsPage />} />
        <Route path="/runs/:runId/findings/:index" element={<FindingPage />} />
        <Route path="/documents/:slug" element={<DocumentPage />} />
        <Route
          path="/documents/:slug/pull-request"
          element={<PullRequestPage />}
        />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </Suspense>
  );
}
