// The season: what the packet scripts (documents arriving, recomputes, the extension, e-file,
// payments, the 2028 notice) and what people did, in time order. Any moment can be replayed.
import { useApi, useApp } from "../api.js";
import { ErrorBox, Loading, Ref } from "../components/common.jsx";
import { describeEvent } from "../events.js";
import { date, dateTime } from "../format.js";

const SEASON_LABEL = {
  engagement_signed: "Engagement signed",
  questionnaire_submitted: "Questionnaire submitted",
  client_marked_upload_complete: "Client marked uploads complete",
  document_received: "Document received",
  return_computed: "Return computed",
  work_started: "Work started",
  irs_transcript_pulled: "IRS transcript pulled",
  staff_joined_engagement: "Staff joined",
  client_call: "Client call",
  extension_filed_with_payment: "Extension filed with payment",
  client_message: "Client message",
  client_approved_and_signed_8879: "Client approved and signed 8879",
  efile_rejected: "E-file rejected",
  efile_accepted_federal: "Federal e-file accepted",
  efile_accepted_california: "California e-file accepted",
  federal_balance_paid: "Federal balance paid",
  california_refund_issued: "California refund issued",
  quality_review_selected_return: "Quality review selected the return",
  next_year_engagement_started: "Next year's engagement started",
  notice_received: "IRS notice received",
};

export default function Timeline({ names, refreshKey }) {
  const { data, error } = useApi("/api/timeline", refreshKey);
  const { asOf, setAsOf } = useApp();
  if (error) return <ErrorBox error={error} />;
  if (!data) return <Loading />;
  return (
    <div className="page narrow">
      <div className="page-head">
        <div>
          <h1>Timeline and replay</h1>
          <p className="muted">
            The season as the packet scripts it, and every act people recorded. Replay to any moment to see the return,
            the documents and the checker as they stood then.
          </p>
        </div>
      </div>
      <ol className="timeline season">
        {data.map((item) => {
          const day = item.at.slice(0, 10);
          const here = asOf === day;
          return (
            <li key={item.id} className={`${item.kind} ${here ? "here" : ""} ${item.undone ? "undone" : ""}`}>
              <span className="muted small">
                {item.kind === "act" ? dateTime(item.at) : date(item.at)}
                {item.kind === "act" && <span className="tag">act</span>}
              </span>
              <span>
                {item.kind === "season" ? (
                  <strong>{SEASON_LABEL[item.event] || item.event}</strong>
                ) : (
                  describeEvent({ ...item, action: item.event, targets: item.refs }, names)
                )}
                {item.kind === "season" && item.actor && <span className="muted"> · {names[item.actor] || item.actor}</span>}
              </span>
              {item.detail && <span className="small muted">{item.detail}</span>}
              <span className="refs">
                {item.refs.slice(0, 6).map((r) => (
                  <Ref key={r} value={r} />
                ))}
              </span>
              <button className="link small" onClick={() => setAsOf(here ? null : day)}>
                {here ? "Back to now" : "Replay to this day"}
              </button>
            </li>
          );
        })}
      </ol>
    </div>
  );
}
