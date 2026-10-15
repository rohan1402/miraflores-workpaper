// Answering a notice (D24). The firm drafts an answer per item with the evidence it rests on; the
// partner previews the package and releases it. The examiner sees only what was released.
import { useState } from "react";
import { getJSON, useApi } from "../api.js";
import { ErrorBox, Loading, Ref } from "../components/common.jsx";
import { ActionBar, useCan } from "../components/Act.jsx";
import { NoticeResponseForm, ReleaseNoticeForm } from "../components/Forms.jsx";
import ResponsePackage from "../components/ResponsePackage.jsx";
import { date, dateTime } from "../format.js";
import { href } from "../router.js";

export default function Notice({ names, refreshKey }) {
  const { data, error } = useApi("/api/notices", refreshKey);
  if (error) return <ErrorBox error={error} />;
  if (!data) return <Loading />;
  return (
    <div className="page narrow">
      <div className="page-head">
        <div>
          <h1>Notices</h1>
          <p className="muted">
            A notice about this return arrives only after the return was accepted. The answer goes out as a self-contained
            record: the figures as filed, traced to their pages, with no internal notes.
          </p>
        </div>
      </div>
      {data.notices.length === 0 && (
        <p className="muted">
          No notice. The 2028 Letter 566 arrives on January 26, 2028, and only if a return was accepted (see{" "}
          <a href={href.filing()}>Filing</a>).
        </p>
      )}
      {data.notices.map((n) => (
        <NoticeCard key={n.id} notice={n} tip={data.meta.tip} names={names} />
      ))}
    </div>
  );
}

function NoticeCard({ notice, tip, names }) {
  const can = useCan();
  const [preview, setPreview] = useState(null);
  const showPreview = async () => setPreview(preview ? null : await getJSON(`/api/notices/preview?notice=${encodeURIComponent(notice.ref)}`));
  return (
    <section>
      <h2>
        {notice.agency} {notice.type}
      </h2>
      <p className="small muted">
        Dated {date(`${notice.dated}T12:00:00Z`)}; response due {date(`${notice.response_due}T12:00:00Z`)}.{" "}
        {notice.document && <Ref value={notice.document} />}
      </p>
      {notice.items.map((item) => (
        <article key={item.item} className="card">
          <h3>Item {item.item + 1}</h3>
          <p className="examined">{item.text}</p>
          {item.draft ? (
            <div className="small">
              <strong>Draft answer</strong> ({names[item.draft.by] || item.draft.by}, {dateTime(item.draft.at)}): {item.draft.text}
              <div className="refs">
                {item.draft.evidence.map((r) => (
                  <Ref key={r} value={r} />
                ))}
              </div>
            </div>
          ) : (
            <p className="small muted">No answer yet. Suggested evidence: {item.suggested.join(", ")}</p>
          )}
          <ActionBar actions={[
            { key: "answer", label: item.draft ? "Revise the answer" : "Write the answer", primary: !item.draft,
              allowed: can("notice_response"), render: (done) => <NoticeResponseForm notice={notice} item={item} tip={tip} onDone={done} /> },
          ]} />
        </article>
      ))}
      <div className="card">
        <h3>Release</h3>
        {notice.released.length > 0 ? (
          <p className="small">
            Released {dateTime(notice.released.at(-1).at)} by {names[notice.released.at(-1).by] || notice.released.at(-1).by}.
            {notice.changed_since_release && <span className="tag warn"> drafts changed since; release again to send them</span>}
          </p>
        ) : (
          <p className="small muted">Not released. The examiner sees nothing until the partner releases it.</p>
        )}
        <button className="link small" onClick={showPreview}>
          {preview ? "Hide the preview" : "Preview what the examiner will see"}
        </button>
        {notice.released.length > 0 && (
          <>
            {" · "}
            <a className="small" href={href.examiner()}>
              Open the examiner's view
            </a>
          </>
        )}
        {preview && <ResponsePackage pkg={preview} />}
        <ActionBar actions={[
          { key: "release", label: "Release to the examiner", primary: true, allowed: can("release_notice_response"),
            render: (done) => <ReleaseNoticeForm notice={notice} tip={tip} onDone={done} /> },
        ]} />
      </div>
    </section>
  );
}
