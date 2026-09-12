type LogFields = Record<string, unknown>;

function scrub(fields: LogFields): LogFields {
  const out: LogFields = {};
  for (const [k, v] of Object.entries(fields)) {
    const key = k.toLowerCase();
    if (key.includes('password') || key.includes('token') || key.includes('secret')) {
      out[k] = '[redacted]';
    } else {
      out[k] = v;
    }
  }
  return out;
}

export function logRequest(fields: LogFields) {
  const line = {
    ts: new Date().toISOString(),
    ...scrub(fields),
  };
  if (fields.level === 'error') {
    console.error(JSON.stringify(line));
  } else {
    console.info(JSON.stringify(line));
  }
}
