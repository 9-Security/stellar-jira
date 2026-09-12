import { describe, expect, it } from 'vitest';
import {
  IllegalTransitionError,
  assertOpportunityTransition,
  assertTicketTransition,
  assertScheduleTransition,
} from '@crm/shared';

describe('status machines', () => {
  it('allows listed opportunity edges and rejects others', () => {
    expect(() => assertOpportunityTransition('lead', 'negotiating')).not.toThrow();
    expect(() => assertOpportunityTransition('won', 'lost')).toThrow(
      IllegalTransitionError,
    );
    expect(() => assertOpportunityTransition('lost', 'negotiating')).not.toThrow();
  });

  it('allows listed ticket edges', () => {
    expect(() => assertTicketTransition('open', 'in_progress')).not.toThrow();
    expect(() => assertTicketTransition('open', 'closed')).toThrow(
      IllegalTransitionError,
    );
  });

  it('treats completed/cancelled schedules as terminal', () => {
    expect(() => assertScheduleTransition('scheduled', 'cancelled')).not.toThrow();
    expect(() => assertScheduleTransition('completed', 'scheduled')).toThrow(
      IllegalTransitionError,
    );
  });
});
