import { create } from 'zustand'
import type { OperationalDraft } from '@/components/DepotOperationalOverrideForm'

interface RoutePlanDrafts {
  drafts: Record<string, OperationalDraft>
  setDraft: (key: string, draft: OperationalDraft) => void
  clearDraft: (key: string) => void
}

export const useRoutePlanDrafts = create<RoutePlanDrafts>((set) => ({
  drafts: {},
  setDraft: (key, draft) => set((state) => ({ drafts: { ...state.drafts, [key]: draft } })),
  clearDraft: (key) => set((state) => {
    const drafts = { ...state.drafts }
    delete drafts[key]
    return { drafts }
  }),
}))
