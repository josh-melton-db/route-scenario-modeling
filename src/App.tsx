import { BrowserRouter, Navigate, Route, Routes, useParams } from 'react-router-dom'
import { Layout } from './components/Layout'
import BaselinePage from './pages/BaselinePage'
import DataEditorPage from './pages/DataEditorPage'
import OptimizationRunsPage from './pages/OptimizationRunsPage'
import ScenarioBuilderPage from './pages/ScenarioBuilderPage'
import RatesPage from './pages/RatesPage'
import ContractDetailPage from './pages/ContractDetailPage'
import NetworkPage from './pages/NetworkPage'

export default function App() {
  return (
    <BrowserRouter>
      <Layout>
        <Routes>
          <Route path="/" element={<Navigate to="/network" replace />} />
          <Route path="/network" element={<NetworkPage />} />
          <Route path="/analyze" element={<BaselinePage />} />
          <Route path="/baseline" element={<Navigate to="/analyze" replace />} />
          <Route path="/scenario" element={<ScenarioBuilderPage />} />
          <Route path="/rates" element={<RatesPage />} />
          <Route path="/rates/contracts/:contractId/versions/:versionId/:tab?" element={<ContractDetailPage />} />
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
