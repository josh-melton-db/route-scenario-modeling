import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from '@/api/client'
import type { NetworkBaselineProposal } from '@/api/types'

// Kept compact so lifecycle controls do not take space away from the flow map.
export default function NetworkBaselineActions({ runId }: { runId?: string }) {
  const client = useQueryClient()
  const baseline = useQuery({ queryKey: ['network-baseline'], queryFn: api.networkBaseline })
  const [proposal, setProposal] = useState<NetworkBaselineProposal | null>(null)
  const action = useMutation({
    mutationFn: async (kind: 'propose' | 'accept') => {
      if (kind === 'propose') {
        if (!runId) throw new Error('A solved network run is required.')
        setProposal(await api.proposeNetworkBaseline(runId))
      } else if (kind === 'accept') {
        if (!proposal || proposal.run_id !== runId) throw new Error('Propose this run first.')
        await api.acceptNetworkBaseline(proposal.proposal_id)
        setProposal(null)
      }
      await client.invalidateQueries({ queryKey: ['network-baseline'] })
      await client.invalidateQueries({ queryKey: ['network-overview'] })
      await client.invalidateQueries({ queryKey: ['network-options'] })
      await client.invalidateQueries({ queryKey: ['network-baseline-plan-run'] })
    },
  })
  const state = baseline.data
  const isActive = Boolean(runId && state?.active_run_id === runId)
  const currentProposal = proposal?.run_id === runId ? proposal : null
  const buttonClass = 'rounded-md border border-border px-3 py-1.5 text-xs font-medium hover:bg-accent/50 disabled:opacity-50'
  return (
    <section aria-label="Network baseline lifecycle" className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
      <span>{baseline.isLoading ? 'Loading baseline revision…' : state ? (state.active_run_id ? 'Accepted network baseline' : 'Original story baseline') : 'Baseline revision unavailable'}</span>
      {state?.accepted_at && <span>· accepted {new Date(state.accepted_at).toLocaleDateString()}</span>}
      {isActive ? <span className="text-primary">This run is the active baseline</span> : runId && (
        <button className={buttonClass} disabled={action.isPending || !state} onClick={() => action.mutate(currentProposal ? 'accept' : 'propose')}>
          {currentProposal ? 'Accept as baseline' : 'Propose as baseline'}
        </button>
      )}
      {currentProposal && (
        <span>Proposal ready · history retained · {currentProposal.route_coverage?.message ?? 'Local routes pending'}</span>
      )}
      {state?.active_run_id && state.route_coverage && <span>· {state.route_coverage.message}</span>}
      {(action.error || baseline.error) && <p role="alert" className="w-full text-destructive">{String(action.error || baseline.error)}</p>}
    </section>
  )
}
