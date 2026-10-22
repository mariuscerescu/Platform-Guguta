"use client";

import { useRef } from "react";
import { withBase } from "../../lib/paths";

const SURVEY_URL = "https://tineri.math.md/edu-platform/sondaj";

export default function SurveyQr() {
  const dialog = useRef<HTMLDialogElement>(null);
  return <>
    <button className="survey-qr-button" type="button" aria-label="Mărește codul QR pentru sondaj" onClick={() => dialog.current?.showModal()}>
      <img src={withBase("/survey-qr.svg")} width={72} height={72} alt="Cod QR către sondajul Guguță" />
      <span>Scanează sondajul<small>Apasă pentru mărire</small></span>
    </button>
    <dialog ref={dialog} className="survey-qr-dialog" aria-labelledby="survey-qr-title" onClick={event => {
      if (event.target === event.currentTarget) dialog.current?.close();
    }}>
      <div className="survey-qr-heading"><h2 id="survey-qr-title">Scanează și completează sondajul</h2>
        <button type="button" aria-label="Închide codul QR" onClick={() => dialog.current?.close()}>×</button>
      </div>
      <img src={withBase("/survey-qr.svg")} width={640} height={640} alt="Cod QR către https://tineri.math.md/edu-platform/sondaj" />
      <a href={SURVEY_URL}>tineri.math.md/edu-platform/sondaj</a>
    </dialog>
  </>;
}
