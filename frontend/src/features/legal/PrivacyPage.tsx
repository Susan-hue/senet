import { LegalPage } from "./LegalPage";
import type { LegalSection } from "./LegalPage";
import styles from "./legal.module.css";

const CONTACT_EMAIL = "privacy@senet.ng";

const SECTIONS: LegalSection[] = [
  {
    heading: "Who controls your data",
    body: (
      <>
        <p>
          Your institution is the <strong>data controller</strong> for the records it holds in
          Senet. It decides what is collected, who inside the university may see it, and how long it
          is kept. Senet operates as the <strong>data processor</strong>: we hold and process that
          data on the institution&rsquo;s written instructions and for no other purpose.
        </p>
        <p>
          We do not sell personal data, we do not use student records to train models, and we do not
          share data between institutions. Each institution&rsquo;s data is isolated from every
          other institution&rsquo;s at the database level.
        </p>
      </>
    ),
  },
  {
    heading: "What we collect, and why",
    body: (
      <>
        <p>Senet holds only what running a university&rsquo;s academic operations requires.</p>
        <table className={styles.table}>
          <thead>
            <tr>
              <th>Category</th>
              <th>Examples</th>
              <th>Why it is held</th>
            </tr>
          </thead>
          <tbody>
            <tr>
              <td>Identity and account</td>
              <td>Name, email address, matric or staff number, role, faculty and department</td>
              <td>To sign you in and decide what you may see and do</td>
            </tr>
            <tr>
              <td>Academic records</td>
              <td>Enrolments, continuous assessment scores, exam scores, grades, GPA and CGPA</td>
              <td>To produce and approve results, and to maintain the academic record</td>
            </tr>
            <tr>
              <td>Examination data</td>
              <td>Answers submitted, timing, and the paper drawn for each attempt</td>
              <td>To mark exams and resolve disputes about an attempt</td>
            </tr>
            <tr>
              <td>Proctoring data</td>
              <td>
                Tab switches, loss of window focus, fullscreen exits, clipboard events, and webcam
                snapshots or short clips where the institution enables them
              </td>
              <td>To let a human reviewer assess exam integrity</td>
            </tr>
            <tr>
              <td>Contact preferences</td>
              <td>Phone number, and a hashed PIN if you register for the SMS result check</td>
              <td>To notify you, and to verify you before releasing a result over SMS</td>
            </tr>
            <tr>
              <td>Audit trail</td>
              <td>Who changed which score or approval, when, and why</td>
              <td>
                To make the results process reviewable &mdash; a legal and accreditation requirement
              </td>
            </tr>
          </tbody>
        </table>
      </>
    ),
  },
  {
    id: "proctoring",
    heading: "Proctoring and webcam capture",
    body: (
      <>
        <p>
          Where an institution enables proctoring, Senet records signals from the exam browser and
          may capture <strong>webcam snapshots or short clips during an exam attempt</strong>. This
          is stated before an attempt begins; a student who does not consent should not start the
          attempt and should contact their exam officer.
        </p>
        <p>Limits that apply to all proctoring data:</p>
        <ul>
          <li>
            It is <strong>evidence for human review only</strong>. It never automatically changes a
            score, a grade or the outcome of an attempt.
          </li>
          <li>
            An integrity flag is a request for a person to look, not a finding of misconduct. Only a
            reviewer can dismiss it or escalate it, and any consequence follows the
            institution&rsquo;s own disciplinary process.
          </li>
          <li>
            Access is restricted to the assigned lecturer, the exam officer and staff in scope.
            Other students never have access, and neither does anyone at another institution.
          </li>
          <li>
            Captures are stored with restricted access and deleted when their retention window
            expires.
          </li>
        </ul>
      </>
    ),
  },
  {
    heading: "How long we keep it",
    body: (
      <>
        <ul>
          <li>
            <strong>Academic records and audit trail</strong> &mdash; retained for the life of the
            student record. Nigerian universities are required to keep results permanently, and
            ratified results are immutable by design.
          </li>
          <li>
            <strong>Webcam captures</strong> &mdash; deleted after the retention window the
            institution configures, 90 days by default.
          </li>
          <li>
            <strong>Proctoring event logs</strong> &mdash; retained with the exam attempt they
            belong to.
          </li>
          <li>
            <strong>Notification logs</strong> &mdash; retained as a delivery record of what was
            sent and whether it arrived.
          </li>
          <li>
            <strong>Account data</strong> &mdash; retained while your institution maintains your
            account.
          </li>
        </ul>
        <p>
          Retention periods are set by your institution within these bounds. A request to delete
          data should go to your institution first, as the controller.
        </p>
      </>
    ),
  },
  {
    id: "ndpa",
    heading: "Your rights under the NDPA 2023",
    body: (
      <>
        <p>
          The Nigeria Data Protection Act 2023 gives you rights over your personal data. Through
          your institution, you may:
        </p>
        <ul>
          <li>
            <strong>Access</strong> the personal data held about you, and be told why it is held.
          </li>
          <li>
            <strong>Correct</strong> data that is inaccurate or incomplete. Corrections to a
            ratified result run through the formal amendment process, which keeps the original
            record intact and adds the correction on top &mdash; that history is deliberate and
            cannot be erased.
          </li>
          <li>
            <strong>Object</strong> to a particular processing activity, or withdraw consent where
            processing rests on consent.
          </li>
          <li>
            <strong>Request deletion</strong> where there is no lawful basis or statutory duty to
            keep the data. Academic records generally cannot be deleted, as the institution is
            legally required to retain them.
          </li>
          <li>
            <strong>Request a portable copy</strong> of your data in a common format.
          </li>
          <li>
            <strong>Complain</strong> to the Nigeria Data Protection Commission (NDPC) if you
            believe your rights have been breached.
          </li>
        </ul>
        <p>
          Because your institution is the controller, start with its data protection officer or
          registrar. We support institutions in answering these requests and will act on their
          instructions.
        </p>
      </>
    ),
  },
  {
    heading: "Accreditation and third-party access",
    body: (
      <>
        <p>
          For accreditation, an institution may grant a body such as the National Universities
          Commission a <strong>read-only</strong> vault token, limited to named programmes and
          sessions, with an expiry date, revocable at any time. Such access can never write to or
          alter any record, and every request made with it is logged.
        </p>
        <p>
          Senet also uses processors to operate the service: cloud hosting and database, email
          delivery, and SMS/WhatsApp delivery for notifications. They act on our instructions and
          receive only what their function requires.
        </p>
      </>
    ),
  },
  {
    heading: "Security",
    body: (
      <ul>
        <li>Data is isolated per institution and access is scoped by role.</li>
        <li>Passwords and result-check PINs are stored hashed, never in readable form.</li>
        <li>
          Ratified results are protected by database-level rules, so they cannot be rewritten even
          by a direct query.
        </li>
        <li>Score changes and approvals are written to an append-only audit trail.</li>
        <li>Results released over SMS or USSD require the registered phone, matric and PIN.</li>
      </ul>
    ),
  },
  {
    heading: "Contact",
    body: (
      <p>
        For questions about this policy, write to{" "}
        <a href={`mailto:${CONTACT_EMAIL}`}>{CONTACT_EMAIL}</a>. For a request about your own
        records, contact your institution&rsquo;s data protection officer or registrar, who is the
        controller of that data.
      </p>
    ),
  },
];

export function PrivacyPage() {
  return (
    <LegalPage
      title="Privacy Policy"
      updated="29 July 2026"
      intro={
        <p>
          This policy explains what personal data Senet holds on behalf of the universities that use
          it, why it is held, how long it is kept, and the rights you have over it under the Nigeria
          Data Protection Act 2023.
        </p>
      }
      sections={SECTIONS}
    />
  );
}
