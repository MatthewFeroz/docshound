import { Component, lazy, Suspense, type ReactNode } from "react";
import { Navigate, Route, Routes, useLocation } from "react-router-dom";
import "easymde/dist/easymde.min.css";

import { ErrorMessage, Loading } from "./components/Status";
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

// A page chunk can fail to load, for example after a redeploy replaces it.
class PageLoadBoundary extends Component<
  { children: ReactNode },
  { failed: boolean }
> {
  state = { failed: false };

  static getDerivedStateFromError() {
    return { failed: true };
  }

  render() {
    if (this.state.failed)
      return (
        <main>
          <ErrorMessage message="This page could not be loaded. Reload the page to try again." />
        </main>
      );
    return this.props.children;
  }
}

export default function App() {
  const { pathname } = useLocation();
  return (
    <PageLoadBoundary key={pathname}>
      <Suspense fallback={<Loading label="Loading page…" />}>
        <Routes>
          <Route path="/" element={<HomePage />} />
          <Route
            path="/showcase"
            element={<Navigate to="/#overview" replace />}
          />
          <Route path="/usage" element={<UsagePage />} />
          <Route path="/findings" element={<FindingsPage />} />
          <Route
            path="/runs/:runId/findings/:index"
            element={<FindingPage />}
          />
          <Route path="/documents/:slug" element={<DocumentPage />} />
          <Route
            path="/documents/:slug/pull-request"
            element={<PullRequestPage />}
          />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </Suspense>
    </PageLoadBoundary>
  );
}
