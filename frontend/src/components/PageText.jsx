// Printed page text with marks: where a value is printed (highlight) and the passages a finding
// relies on (underlined). The text is the truth; the server has already masked anything sensitive.

// The ways a value can be printed: as the pipeline read it, or formatted from the value.
export function valueNeedles(value) {
  if (!value) return [];
  const list = [];
  if (value.text_as_read) list.push(String(value.text_as_read));
  if (typeof value.value === "number") {
    list.push(value.value.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 }));
    list.push(value.value.toLocaleString("en-US"));
  } else if (value.value !== null && value.value !== undefined) {
    list.push(String(value.value));
  }
  return list.filter((s) => s && s.length > 1);
}

// A read value as it would be printed: money with cents, counts with separators, text as is.
export function printedValue(v) {
  if (v.value === null || v.value === undefined) return "nothing read";
  if (typeof v.value === "number" && ["money", "integer", "quantity"].includes(v.value_type)) {
    return v.value.toLocaleString("en-US", v.value_type === "money" ? { minimumFractionDigits: 2, maximumFractionDigits: 2 } : {});
  }
  return String(v.value);
}

// marks: [{ needles: [string], kind: "value" | "selected" | "quote", title }]
export default function PageText({ text, marks = [], className = "" }) {
  const ranges = [];
  for (const mark of marks) {
    for (const needle of mark.needles) {
      const at = findFree(text, needle, ranges);
      if (at >= 0) {
        ranges.push({ start: at, end: at + needle.length, kind: mark.kind, title: mark.title });
        break;
      }
    }
  }
  ranges.sort((a, b) => a.start - b.start);
  const parts = [];
  let cursor = 0;
  ranges.forEach((r, i) => {
    if (r.start > cursor) parts.push(text.slice(cursor, r.start));
    parts.push(
      <mark key={i} className={`mk mk-${r.kind}`} title={r.title}>
        {text.slice(r.start, r.end)}
      </mark>,
    );
    cursor = r.end;
  });
  parts.push(text.slice(cursor));
  return <div className={`page-text ${className}`}>{parts}</div>;
}

// The first occurrence of `needle` that does not overlap a range already marked.
function findFree(text, needle, ranges) {
  let from = 0;
  while (from <= text.length) {
    const at = text.indexOf(needle, from);
    if (at < 0) return -1;
    const end = at + needle.length;
    if (!ranges.some((r) => at < r.end && end > r.start)) return at;
    from = at + 1;
  }
  return -1;
}
