import type {
  ActivityStatus,
  OpportunityStage,
  ScheduleStatus,
  TicketStatus,
} from './enums';

/** Allowed next statuses. Illegal transitions must return 409/422. */
export const OPPORTUNITY_TRANSITIONS: Record<OpportunityStage, OpportunityStage[]> = {
  lead: ['negotiating', 'lost'],
  negotiating: ['quoted', 'lost'],
  quoted: ['won', 'lost', 'negotiating'],
  won: ['negotiating'],
  lost: ['negotiating'],
};

export const TICKET_TRANSITIONS: Record<TicketStatus, TicketStatus[]> = {
  open: ['in_progress'],
  in_progress: ['pending_reply', 'resolved'],
  pending_reply: ['in_progress', 'resolved'],
  resolved: ['closed', 'in_progress'],
  closed: ['open'],
};

export const SCHEDULE_TRANSITIONS: Record<ScheduleStatus, ScheduleStatus[]> = {
  scheduled: ['in_progress', 'cancelled'],
  in_progress: ['completed', 'cancelled'],
  completed: [],
  cancelled: [],
};

export const ACTIVITY_TRANSITIONS: Record<ActivityStatus, ActivityStatus[]> = {
  todo: ['done'],
  done: ['todo'],
};

export type EntityKind = 'opportunity' | 'ticket' | 'schedule' | 'activity';

export class IllegalTransitionError extends Error {
  readonly from: string;
  readonly to: string;
  readonly entity: EntityKind;

  constructor(entity: EntityKind, from: string, to: string) {
    super(`Illegal ${entity} transition: ${from} → ${to}`);
    this.name = 'IllegalTransitionError';
    this.entity = entity;
    this.from = from;
    this.to = to;
  }
}

function assertEdge<T extends string>(
  entity: EntityKind,
  map: Record<T, T[]>,
  from: T,
  to: T,
): void {
  const allowed = map[from] ?? [];
  if (!allowed.includes(to)) {
    throw new IllegalTransitionError(entity, from, to);
  }
}

export function assertOpportunityTransition(
  from: OpportunityStage,
  to: OpportunityStage,
): void {
  assertEdge('opportunity', OPPORTUNITY_TRANSITIONS, from, to);
}

export function assertTicketTransition(from: TicketStatus, to: TicketStatus): void {
  assertEdge('ticket', TICKET_TRANSITIONS, from, to);
}

export function assertScheduleTransition(from: ScheduleStatus, to: ScheduleStatus): void {
  assertEdge('schedule', SCHEDULE_TRANSITIONS, from, to);
}

export function assertActivityTransition(from: ActivityStatus, to: ActivityStatus): void {
  assertEdge('activity', ACTIVITY_TRANSITIONS, from, to);
}
