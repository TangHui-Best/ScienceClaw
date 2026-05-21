import { describe, expect, it } from 'vitest'

const getCandidateStatusLabel = (status: string) => {
  if (status === 'pending') return '等待处理'
  if (status === 'intent_pruning') return '意图裁剪中'
  if (status === 'intent_prune_retrying') return '意图裁剪重试中'
  if (status === 'running') return '生成中'
  if (status === 'rate_limited') return '限流重试中'
  if (status === 'failed') return '生成失败'
  if (status === 'stale') return '等待更新'
  if (status === 'confidence_rejected') return '置信度不足'
  if (status === 'intent_filtered') return 'AI 过滤'
  if (status === 'intent_review') return '需确认'
  return '已生成'
}

const getPruneDetail = (status: string, intentPruneError?: string | null) => {
  if (!intentPruneError) return ''
  return `${status === 'intent_review' ? '意图裁剪失败，已转人工确认：' : '意图裁剪重试中：'}${intentPruneError}`
}

describe('ApiMonitorPage intent prune candidate display', () => {
  it('labels intent prune running and retrying statuses', () => {
    expect(getCandidateStatusLabel('intent_pruning')).toBe('意图裁剪中')
    expect(getCandidateStatusLabel('intent_prune_retrying')).toBe('意图裁剪重试中')
    expect(getCandidateStatusLabel('pending')).toBe('等待处理')
  })

  it('formats prune retry and final review details', () => {
    expect(getPruneDetail('intent_prune_retrying', 'slow prune')).toBe('意图裁剪重试中：slow prune')
    expect(getPruneDetail('intent_review', 'llm unavailable')).toBe('意图裁剪失败，已转人工确认：llm unavailable')
  })
})
