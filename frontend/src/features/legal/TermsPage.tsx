import { LegalPage } from "./LegalPage";
import type { LegalSection } from "./LegalPage";

const CONTACT_EMAIL = "legal@senet.ng";

const SECTIONS: LegalSection[] = [
  {
    heading: "These terms",
    body: (
      <>
        <p>
          These terms govern use of Senet. Where an institution has signed a separate written
          agreement with us, that agreement governs and these terms fill the gaps.
        </p>
        <p>
          Using Senet means accepting these terms. If you use Senet through your university, you
          also remain bound by your institution&rsquo;s own regulations.
        </p>
      </>
    ),
  },
  {
    heading: "Accounts",
    body: (
      <ul>
        <li>
          Accounts are issued by your institution. You may not create one on someone else&rsquo;s
          behalf or hold an account you were not issued.
        </li>
        <li>
          You are responsible for what happens under your account. Keep your password and your
          result-check PIN to yourself, and do not share either.
        </li>
        <li>
          Tell your institution immediately if you believe your account or your registered phone has
          been compromised.
        </li>
        <li>
          Your role determines what you can see and do. Attempting to reach data outside your role
          is a breach of these terms.
        </li>
      </ul>
    ),
  },
  {
    heading: "Acceptable use",
    body: (
      <>
        <p>You must not:</p>
        <ul>
          <li>
            Attempt to access, alter or delete any record you are not authorised to &mdash;
            particularly another student&rsquo;s results or another institution&rsquo;s data.
          </li>
          <li>
            Interfere with an examination: circumventing proctoring, sitting an exam for someone
            else, or using unauthorised material or assistance during an attempt.
          </li>
          <li>
            Share, publish or sell examination questions, question banks, or unpublished results.
          </li>
          <li>
            Probe, scan or test the security of the service, or attempt to bypass any access
            control, without written permission.
          </li>
          <li>
            Automate or scrape the service in a way that degrades it, or use it to send unsolicited
            messages.
          </li>
          <li>
            Upload malicious code, or content that is unlawful or infringes another&rsquo;s rights.
          </li>
        </ul>
        <p>
          We may suspend access to protect the service or its users. Academic misconduct is handled
          by your institution under its own disciplinary process, not by us.
        </p>
      </>
    ),
  },
  {
    heading: "Institutional responsibilities",
    body: (
      <>
        <p>An institution using Senet is responsible for:</p>
        <ul>
          <li>
            The accuracy of the records it enters, including scores, enrolments and academic
            structure.
          </li>
          <li>
            Issuing, scoping and revoking accounts, and removing access for staff and students who
            leave.
          </li>
          <li>
            Its approval chain: which staff hold HOD, Dean, Exam Officer and Senate roles, and the
            decisions they make. Senet enforces the process; it does not make academic decisions.
          </li>
          <li>
            Deciding whether to enable proctoring and webcam capture, informing students before an
            exam, and setting retention within the configured bounds.
          </li>
          <li>
            Its duties as data controller under the Nigeria Data Protection Act 2023, including
            answering data subject requests.
          </li>
          <li>
            Issuing and revoking accreditation vault tokens, and confirming who receives them.
          </li>
        </ul>
      </>
    ),
  },
  {
    heading: "Results and academic decisions",
    body: (
      <>
        <p>
          Senet records and enforces a results process; it does not set grades. A result is
          published only after it passes lecturer, HOD, Dean and Senate approval. Ratified results
          are immutable, and corrections run through a formal amendment that preserves the original
          record.
        </p>
        <p>
          Any dispute about a mark, a grade or a classification is a matter for your institution
          under its own regulations.
        </p>
      </>
    ),
  },
  {
    heading: "Availability",
    body: (
      <p>
        We aim to keep Senet available and to schedule maintenance away from examination periods,
        but we do not guarantee uninterrupted service unless a signed agreement says otherwise.
        Examinations are built to tolerate a student losing power or network: an interrupted attempt
        resumes against its original deadline.
      </p>
    ),
  },
  {
    heading: "Intellectual property",
    body: (
      <>
        <p>
          Senet, its software and its design remain ours. Using the service grants no ownership of
          it.
        </p>
        <p>
          Content an institution puts into Senet &mdash; student records, question banks, results
          &mdash; remains that institution&rsquo;s. We claim no ownership and use it only to provide
          the service.
        </p>
      </>
    ),
  },
  {
    heading: "Liability",
    body: (
      <>
        <p>
          Senet is provided without warranties beyond those that cannot lawfully be excluded. We do
          not warrant that it will be error-free or continuously available.
        </p>
        <p>
          To the extent the law allows, we are not liable for indirect or consequential loss, loss
          of profit or reputation, or for loss arising from inaccurate data entered by an
          institution or its staff. Where liability cannot be excluded, it is capped at the fees
          paid for the service in the twelve months before the claim.
        </p>
        <p>
          Nothing here excludes liability for fraud, or for anything that cannot lawfully be
          limited.
        </p>
      </>
    ),
  },
  {
    heading: "Termination",
    body: (
      <p>
        An institution may end its use of Senet under its agreement with us. On termination we will
        make its data available for export for an agreed period, then delete it in line with that
        agreement and applicable law. We may suspend an account that breaches these terms or
        threatens the security of the service.
      </p>
    ),
  },
  {
    heading: "Governing law and contact",
    body: (
      <p>
        These terms are governed by the laws of the Federal Republic of Nigeria. Questions go to{" "}
        <a href={`mailto:${CONTACT_EMAIL}`}>{CONTACT_EMAIL}</a>.
      </p>
    ),
  },
];

export function TermsPage() {
  return (
    <LegalPage
      title="Terms of Service"
      updated="29 July 2026"
      intro={
        <p>
          These terms set out how Senet may be used, what institutions using it are responsible for,
          and the limits of our liability.
        </p>
      }
      sections={SECTIONS}
    />
  );
}
