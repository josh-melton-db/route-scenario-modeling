import { lazy, Suspense } from 'react'
import { BrowserRouter, Navigate, Route, Routes, useParams } from 'react-router-dom'
import { Layout } from './components/Layout'

const BaselinePage = lazy(() => import('./pages/BaselinePage'))
const DataEditorPage = lazy(() => import('./pages/DataEditorPage'))
const OptimizationRunsPage = lazy(() => import('./pages/OptimizationRunsPage'))
const ScenarioBuilderPage = lazy(() => import('./pages/ScenarioBuilderPage'))
const RatesPage = lazy(() => import('./pages/RatesPage'))
const ContractDetailPage = lazy(() => import('./pages/ContractDetailPage'))
const NetworkPage = lazy(() => import('./pages/NetworkPage'))
const DcPage = lazy(() => import('./pages/DcPage'))
const NetworkScenarioDetailPage = lazy(() => import('./pages/NetworkScenarioDetailPage'))

export default function App() {
  return (
    <BrowserRouter>
      <Layout>
        <Suspense fallback={<div className="p-8 text-sm text-muted-foreground">Loading workspace…</div>}>
          <Routes>
          <Route path="/" element={<Navigate to="/network" replace />} />
          <Route path="/network" element={<NetworkPage />} />
          <Route path="/network/scenarios" element={<Navigate to="/network" replace />} />
          <Route
            path="/network/scenarios/:scenarioId/:tab?"
            element={<NetworkScenarioDetailPage />}
          />
          <Route path="/dc/:facilityId" element={<DcPage />} />
          <Route path="/analyze" element={<BaselinePage />} />
          <Route path="/baseline" element={<Navigate to="/analyze" replace />} />
          <Route path="/scenario" element={<ScenarioBuilderPage />} />
          <Route path="/rates" element={<RatesPage />} />
          <Route path="/rates/contracts/:contractId/versions/:versionId/:tab?" element={<ContractDetailPage />} />
          <Route path="/data-editor" element={<DataEditorPage />} />
          <Route path="/runs/:runId" element={<OptimizationRunsPage />} />
          <Route path="/comparison/:scenarioId" element={<LegacyComparisonRedirect />} />
          </Routes>
        </Suspense>
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
