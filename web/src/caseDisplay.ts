export type CaseRow = Record<string, unknown>;

export function caseLabel(c: CaseRow): string {
  const number = String(c.case_number || c.middleware_case_id || "").trim();
  if (number) return number;
  const jira = String(c.jira_key || "").trim();
  if (jira) return jira;
  return "未建票";
}

export function isTicketed(c: CaseRow): boolean {
  return caseLabel(c) !== "未建票";
}

export function caseHref(c: CaseRow): string {
  const ref = String(c.case_ref || c.case_number || c.jira_key || c.stellar_case_id || "").trim();
  return ref ? `/cases/${encodeURIComponent(ref)}` : "/cases";
}

export function caseRowKey(c: CaseRow): string {
  return String(c.case_ref || c.case_number || c.jira_key || c.stellar_case_id || Math.random());
}
