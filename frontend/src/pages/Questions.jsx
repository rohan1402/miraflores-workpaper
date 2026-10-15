// The client's own surface (D1): questions from the firm and the client's answers. Answers become evidence.
import { useState } from "react";
import { getJSON, postJSON, useApi } from "../api.js";
import { ErrorBox, Loading } from "../components/common.jsx";
import { dateTime } from "../format.js";

export default function Questions({ me, names, refreshKey }) {
  const [bump, setBump] = useState(0);
  const { data, error } = useApi("/api/client/questions", `${refreshKey}-${bump}`);
  if (error) return <ErrorBox error={error} />;
  if (!data) return <Loading />;
  const isClient = me.person.role === "client";

  return (
    <div className="page narrow">
      <div className="page-head">
        <div>
          <h1>{isClient ? `Hello, ${me.person.name.split(" ")[0]}` : "Client questions"}</h1>
          <p className="muted">
            {isClient
              ? "Questions from your tax team. Your answers go into the workpaper as evidence."
              : "Questions sent to the client, and what they answered."}
          </p>
        </div>
      </div>
      {data.questions.length === 0 && <p className="muted">No questions yet.</p>}
      {data.questions.map(({ question, answers }) => (
        <article key={question.id} className="card question">
          <div className="muted small">
            {names[question.actor] || question.actor} · {dateTime(question.at)}
          </div>
          <p className="q-text">{question.payload.text}</p>
          {answers.map((a) => (
            <blockquote key={a.id}>
              {a.payload.text}
              <div className="muted small">
                {names[a.actor] || a.actor} · {dateTime(a.at)}
              </div>
            </blockquote>
          ))}
          {isClient && <AnswerBox questionId={question.id} onDone={() => setBump((b) => b + 1)} />}
        </article>
      ))}
    </div>
  );
}

function AnswerBox({ questionId, onDone }) {
  const [text, setText] = useState("");
  const [error, setError] = useState(null);
  const send = async () => {
    setError(null);
    try {
      const { tip } = await getJSON("/api/me");
      await postJSON("/api/actions", { action: "answer", targets: [`event:${questionId}`], payload: { text }, base_tip: tip });
      setText("");
      onDone();
    } catch (e) {
      setError(e);
    }
  };
  return (
    <div className="answer-box">
      <textarea value={text} onChange={(e) => setText(e.target.value)} placeholder="Your answer" rows={3} />
      <button className="primary" disabled={!text.trim()} onClick={send}>
        Send answer
      </button>
      <ErrorBox error={error} />
    </div>
  );
}
