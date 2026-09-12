export const ROLES = ['admin', 'sales', 'support', 'engineering'] as const;
export type Role = (typeof ROLES)[number];

export const MEMBERSHIP_STATUSES = ['active', 'disabled'] as const;
export type MembershipStatus = (typeof MEMBERSHIP_STATUSES)[number];

export const OPPORTUNITY_STAGES = [
  'lead',
  'negotiating',
  'quoted',
  'won',
  'lost',
] as const;
export type OpportunityStage = (typeof OPPORTUNITY_STAGES)[number];

export const TICKET_STATUSES = [
  'open',
  'in_progress',
  'pending_reply',
  'resolved',
  'closed',
] as const;
export type TicketStatus = (typeof TICKET_STATUSES)[number];

export const SCHEDULE_STATUSES = [
  'scheduled',
  'in_progress',
  'completed',
  'cancelled',
] as const;
export type ScheduleStatus = (typeof SCHEDULE_STATUSES)[number];

export const SCHEDULE_TYPES = ['field_work', 'booking'] as const;
export type ScheduleType = (typeof SCHEDULE_TYPES)[number];

export const ACTIVITY_STATUSES = ['todo', 'done'] as const;
export type ActivityStatus = (typeof ACTIVITY_STATUSES)[number];

export const PRIORITIES = ['low', 'medium', 'high', 'critical'] as const;
export type Priority = (typeof PRIORITIES)[number];

export const ROLE_LABELS: Record<Role, string> = {
  admin: '管理員',
  sales: '業務',
  support: '客服',
  engineering: '工程',
};

export const OPPORTUNITY_STAGE_LABELS: Record<OpportunityStage, string> = {
  lead: '潛在',
  negotiating: '洽談',
  quoted: '報價',
  won: '成交',
  lost: '失單',
};

export const TICKET_STATUS_LABELS: Record<TicketStatus, string> = {
  open: '開立',
  in_progress: '處理中',
  pending_reply: '待回覆',
  resolved: '完成',
  closed: '關閉',
};

export const SCHEDULE_STATUS_LABELS: Record<ScheduleStatus, string> = {
  scheduled: '已排程',
  in_progress: '進行中',
  completed: '完成',
  cancelled: '取消',
};

export const SCHEDULE_TYPE_LABELS: Record<ScheduleType, string> = {
  field_work: '出勤',
  booking: '預約',
};

export const ACTIVITY_STATUS_LABELS: Record<ActivityStatus, string> = {
  todo: '待辦',
  done: '完成',
};

export const PRIORITY_LABELS: Record<Priority, string> = {
  low: '低',
  medium: '中',
  high: '高',
  critical: '緊急',
};
