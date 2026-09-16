import { describe, expect, it } from 'vitest'
import {
  buildSimilarRuleDraft,
  extractStableDescriptionTerm,
  importDescriptionsMatch,
  propagateImportCategory,
} from './similar-description'

describe('extractStableDescriptionTerm', () => {
  it('extracts IFOOD from PIX QR clutter', () => {
    expect(extractStableDescriptionTerm('PIX QR CODE IFOOD 123456789')).toBe('IFOOD')
  })

  it('extracts NETFLIX from domain-like text', () => {
    expect(extractStableDescriptionTerm('NETFLIX.COM')).toBe('NETFLIX')
  })

  it('returns null for generic PIX to a person', () => {
    expect(extractStableDescriptionTerm('PIX ENVIADO JOAO')).toBeNull()
  })

  it('returns null for empty / noise-only', () => {
    expect(extractStableDescriptionTerm('PIX QR CODE')).toBeNull()
    expect(extractStableDescriptionTerm('')).toBeNull()
  })

  it('prefers merchant over short noise', () => {
    expect(extractStableDescriptionTerm('PAGAMENTO MERCADOLIVRE 998877')).toBe('MERCADOLIVRE')
  })
})

describe('buildSimilarRuleDraft', () => {
  it('marks stable when a term is found', () => {
    const draft = buildSimilarRuleDraft('PIX QR CODE IFOOD 55')
    expect(draft.isStable).toBe(true)
    expect(draft.conditionValue).toBe('IFOOD')
  })

  it('falls back to full description when unstable', () => {
    const draft = buildSimilarRuleDraft('PIX ENVIADO JOAO')
    expect(draft.isStable).toBe(false)
    expect(draft.conditionValue).toBe('PIX ENVIADO JOAO')
  })
})

describe('importDescriptionsMatch', () => {
  it('matches exact Sicredi-style truncated memos', () => {
    expect(
      importDescriptionsMatch('RESTAURANTE E LANCHO     ', 'RESTAURANTE E LANCHO'),
    ).toBe(true)
  })

  it('matches same merchant with different store suffixes', () => {
    expect(importDescriptionsMatch('DROGASIL 3034', 'DROGASIL 3852')).toBe(true)
  })

  it('does not match unrelated merchants', () => {
    expect(importDescriptionsMatch('NETFLIX COM', 'SPOTIFY')).toBe(false)
  })

  it('does not match unstable PIX person transfers together', () => {
    expect(
      importDescriptionsMatch('PIX ENVIADO JOAO', 'PIX ENVIADO MARIA'),
    ).toBe(false)
  })
})

describe('propagateImportCategory', () => {
  const rows = [
    { _id: '1', description: 'DROGASIL 3034', selected_category_id: undefined as string | null | undefined },
    { _id: '2', description: 'DROGASIL 3852' },
    { _id: '3', description: 'NETFLIX COM' },
    { _id: '4', description: 'DROGASIL 3034', selected_category_id: 'other' as string | null },
  ]

  it('fills matching untouched rows and skips a different manual pick', () => {
    const { next, propagated } = propagateImportCategory(rows, '1', 'cat-saude')
    expect(propagated).toBe(1)
    expect(next[0].selected_category_id).toBe('cat-saude')
    expect(next[1].selected_category_id).toBe('cat-saude')
    expect(next[2].selected_category_id).toBeUndefined()
    expect(next[3].selected_category_id).toBe('other')
  })

  it('does not overwrite a sibling already set to another category when clearing', () => {
    const filled = [
      { _id: '1', description: 'DROGASIL 3034', selected_category_id: 'cat-saude' as string | null },
      { _id: '2', description: 'DROGASIL 3852', selected_category_id: 'cat-saude' as string | null },
      { _id: '3', description: 'NETFLIX COM' },
    ]
    const { next, propagated } = propagateImportCategory(filled, '1', null)
    expect(next[0].selected_category_id).toBeNull()
    expect(next[1].selected_category_id).toBe('cat-saude')
    expect(propagated).toBe(0)
  })
})
