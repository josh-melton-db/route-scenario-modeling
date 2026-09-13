import { BrowserRouter, Navigate, Route, Routes, useParams } from 'react-router-dom'
import { Layout } from './components/Layout'
import BaselinePage from './pages/BaselinePage'
import DataEditorPage from './pages/DataEditorPage'
import OptimizationRunsPage from './pages/OptimizationRunsPage'
import ScenarioBuilderPage from './pages/ScenarioBuilderPage'

export default function App() {
  return (
    <BrowserRouter>
      <Layout>
        <Routes>
          <Route path="/" element={<Navigate to="/analyze" replace />} />
          <Route path="/analyze" element={<BaselinePage />} />
          <Route path="/baseline" element={<Navigate to="/analyze" replace />} />
          <Route path="/scenario" element={<ScenarioBuilderPage />} />
          <Route path="/data-editor" element={<DataEditorPage />} />
          <Route path="/runs/:runId" element={<OptimizationRunsPage />} />
          <Route path="/comparison/:scenarioId" element={<LegacyComparisonRedirect />} />
        </Routes>
      </Layout>
    </BrowserRouter>
  )
}

function LegacyComparisonRedirect() {
  const { scenarioId } = useParams()
  return (
    <Navigate
      to={`/analyze?compare=${encodeURIComponent(scenarioId ?? '')}`}
      replace
    />
  )
}
