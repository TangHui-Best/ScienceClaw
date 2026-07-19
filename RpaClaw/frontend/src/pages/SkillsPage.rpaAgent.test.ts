// @vitest-environment jsdom

import { createApp, nextTick } from 'vue';
import { describe, expect, it, vi } from 'vitest';

const push = vi.fn(); const createSession = vi.fn();
vi.mock('vue-router', () => ({ useRouter: () => ({ push }) }));
vi.mock('vue-i18n', () => ({ useI18n: () => ({ t: (value: string) => value }) }));
vi.mock('../api/agent', () => ({
  getSkills: vi.fn().mockResolvedValue([]), blockSkill: vi.fn(), deleteSkill: vi.fn(),
  createSession: (...args: unknown[]) => createSession(...args),
}));

describe('SkillsPage RPA Agent entry', () => {
  it('creates a generic browser host session before navigating to Recorder', async () => {
    createSession.mockResolvedValue({ session_id: 'host-session-1', mode: 'browser' });
    const { default: Page } = await import('./SkillsPage.vue');
    const root = document.createElement('div'); document.body.appendChild(root); const app = createApp(Page); app.mount(root); await nextTick();
    root.querySelector<HTMLButtonElement>('[data-testid="record-skill"]')!.click(); await Promise.resolve(); await nextTick();
    expect(createSession).toHaveBeenCalledWith({ mode: 'browser' });
    expect(push).toHaveBeenCalledWith({ path: '/rpa/recorder', query: { browserSessionRef: 'host-session-1' } });
    app.unmount();
  });
});
