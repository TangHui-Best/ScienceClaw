// @vitest-environment jsdom

import { createApp, nextTick } from 'vue';
import { describe, expect, it } from 'vitest';

describe('RpaStepTimeline intent-first view model', () => {
  it('renders independent execution/replay/compile states and nested observations', async () => {
    const { default: Timeline } = await import('./RpaStepTimeline.vue');
    const root = document.createElement('div');
    document.body.appendChild(root);
    const app = createApp(Timeline, { steps: [
      {
        id: 'manual-1', ordinal: 1, kind: 'manual', title: '点击查询', description: '点击查询',
        label: '手工', action: 'manual', captureStatus: 'captured', executionStatus: 'succeeded',
        replayStatus: 'deterministic_ready', compileMode: 'playwright', observations: [],
        isEffect: false, is_action: true, validation: { status: 'deterministic_ready', details: '已完成' },
      },
      {
        id: 'ai-1', ordinal: 2, kind: 'ai_instruction', title: '获取 star 数', description: '获取 star 数',
        label: 'AI', action: 'agent', captureStatus: 'observing', executionStatus: 'running',
        replayStatus: 'insufficient_evidence', compileMode: 'agent',
        observations: [{ trace_id: 'child-1', action: 'click', summary: '打开项目详情' }],
        isEffect: false, is_action: true, validation: { status: 'insufficient_evidence', details: '执行中' },
      },
    ] });
    app.mount(root);
    await nextTick();
    expect(root.textContent).toContain('已完成');
    expect(root.textContent).toContain('可确定回放');
    expect(root.textContent).toContain('Playwright');
    expect(root.textContent).toContain('运行时 AI');
    expect(root.querySelectorAll('article')).toHaveLength(2);
    expect(root.textContent).not.toContain('打开项目详情');
    root.querySelectorAll<HTMLButtonElement>('article > button')[1].click();
    await nextTick();
    expect(root.textContent).toContain('打开项目详情');
    expect(root.querySelectorAll('[data-testid="timeline-details"]')).toHaveLength(1);
    app.unmount();
  });
});
