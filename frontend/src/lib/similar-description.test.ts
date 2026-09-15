import { describe, expect, it } from 'vitest'
import { buildSimilarRuleDraft, extractStableDescriptionTerm } from './similar-description'

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
