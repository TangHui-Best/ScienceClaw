// @vitest-environment jsdom

import { createApp, nextTick } from 'vue';
import { describe, expect, it } from 'vitest';

describe('RpaStepTimeline greenfield view model', () => {
  it('renders accepted/pending/rejected and nested effect without legacy fallbacks', async () => {
    const { default: Timeline } = await import('./RpaStepTimeline.vue');
    const root = document.createElement('div'); document.body.appendChild(root);
    const app = createApp(Timeline, { steps: [
      { id: 'a', status: 'pending', title: '等待结算', label: 'click', parentId: null, isEffect: false },
      { id: 'b', status: 'accepted', title: '点击查询', label: 'click', parentId: null, isEffect: false },
      { id: 'b-effect', status: 'effect', title: '页面导航', label: 'navigation', parentId: 'trace-b', isEffect: true },
      { id: 'c', status: 'rejected', title: '录制失败', label: 'fill', parentId: null, isEffect: false },
    ] }); app.mount(root); await nextTick();
    expect(root.textContent).toContain('待结算'); expect(root.textContent).toContain('已确认'); expect(root.textContent).toContain('已拒绝');
    expect(root.querySelector('[data-effect-child="true"]')?.textContent).toContain('不额外增加录制步骤');
    expect(root.textContent).not.toContain('CoreTrace');
    app.unmount();
  });
});
