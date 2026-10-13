import { describe, expect, it } from 'vitest';
import type { Job } from '@/api/types';
import { finishedJobs } from '@/stores/jobs';

const job = (id: string, status: string): Job => ({
  id, status, kind: 'process', demo_id: 'd', stage: null, message: null, created_at: 0, updated_at: 0,
});

describe('finishedJobs', () => {
  it('reports jobs that went from active to done/failed', () => {
    const prev = [job('a', 'running'), job('b', 'queued'), job('c', 'done')];
    const next = [job('a', 'done'), job('b', 'running'), job('c', 'done')];
    expect(finishedJobs(prev, next, new Set()).map((j) => j.id)).toEqual(['a']);
  });

  it('reports watched jobs that finished before we ever saw them active', () => {
    expect(finishedJobs([], [job('x', 'failed'), job('y', 'done')], new Set(['x'])).map((j) => j.id)).toEqual(['x']);
  });
});
