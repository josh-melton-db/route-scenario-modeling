import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom'
import { Layout } from './components/Layout'
import BaselinePage from './pages/BaselinePage'
import ComparisonPage from './pages/ComparisonPage'
import DataEditorPage from './pages/DataEditorPage'
import OptimizationRunsPage from './pages/OptimizationRunsPage'
import ScenarioBuilderPage from './pages/ScenarioBuilderPage'

export default function App() {
  return (
    <BrowserRouter>
      <Layout>
        <Routes>
          <Route path="/" element={<Navigate to="/baseline" replace />} />
          <Route path="/baseline" element={<BaselinePage />} />
          <Route path="/scenario" element={<ScenarioBuilderPage />} />
          <Route path="/data-editor" element={<DataEditorPage />} />
          <Route path="/runs/:runId" element={<OptimizationRunsPage />} />
          <Route path="/comparison/:scenarioId" element={<ComparisonPage />} />
        </Routes>
      </Layout>
    </BrowserRouter>
  )
}
