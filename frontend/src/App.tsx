import { Navigate, Route, Routes, useParams, useSearchParams } from 'react-router-dom';

import AppLayout from './components/app/AppLayout';
import ExplorePage from './pages/ExplorePage';
import HomePage from './pages/HomePage';
import ResultsPage from './pages/ResultsPage';
import SavedPage from './pages/SavedPage';
import StepsPage from './pages/StepsPage';
import WelcomePage from './pages/WelcomePage';
import { AppStateProvider } from './state/AppStateProvider';

/** 旧 /explore?run_id=... からの移動。run_id はそのまま引き継ぐ。 */
function LegacyExploreRedirect() {
  const [params] = useSearchParams();
  const runId = params.get('run_id');
  return <Navigate to={`/app/explore${runId ? `?run_id=${runId}` : ''}`} replace />;
}

/** 旧 /opportunities/:id は結果画面を開いて詳細ダイアログを出す。 */
function LegacyDetailRedirect() {
  const { id } = useParams<{ id: string }>();
  return <Navigate to={`/app/results${id ? `?detail=${id}` : ''}`} replace />;
}

export default function App() {
  return (
    <Routes>
      <Route path="/" element={<WelcomePage />} />

      <Route
        element={
          <AppStateProvider>
            <AppLayout />
          </AppStateProvider>
        }
      >
        <Route path="/app" element={<HomePage />} />
        <Route path="/app/explore" element={<ExplorePage />} />
        <Route path="/app/results" element={<ResultsPage />} />
        <Route path="/app/saved" element={<SavedPage />} />
        <Route path="/app/steps" element={<StepsPage />} />
      </Route>

      {/* 移植前の URL を残しておく。 */}
      <Route path="/profile" element={<Navigate to="/app?edit=1" replace />} />
      <Route path="/explore" element={<LegacyExploreRedirect />} />
      <Route path="/opportunities" element={<Navigate to="/app/results" replace />} />
      <Route path="/opportunities/:id" element={<LegacyDetailRedirect />} />

      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}
