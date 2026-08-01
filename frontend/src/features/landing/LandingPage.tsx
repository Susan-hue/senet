import { Link } from "react-router-dom";
import { PublicLayout } from "../../components/PublicLayout";
import { useAuth } from "../../hooks";
import { HeroVisual } from "./HeroVisual";
import styles from "./landing.module.css";

/** The full operational surface, grouped the way a university is actually run.
 *  Breadth is the point here; the three differentiator cards below carry depth. */
const SCOPE = [
  {
    title: "Course content & delivery",
    items: [
      "Course management across every faculty and department",
      "Materials and content delivered to enrolled students",
      "Lesson modules with structured learning paths",
      "Announcements and course-wide communication",
      "Discussion forums and collaborative learning",
    ],
  },
  {
    title: "Assignments & assessment",
    items: [
      "Continuous assessment: assignments, tests, projects",
      "Online submission with deadlines and file limits",
      "A gradebook that feeds straight into results",
      "Rubric-based grading and feedback delivery",
      "Peer review and collaborative assignments",
    ],
  },
  {
    title: "Computer-based testing",
    items: [
      "Question banks per course, reusable across terms",
      "Computer-based tests drawn per student",
      "Automatic marking, with manual marking where it is needed",
      "Proctoring: lockdown signals and webcam capture",
      "Resilient exams that survive network interruptions",
    ],
  },
  {
    title: "Records & results",
    items: [
      "The lecturer → HOD → Dean → Senate approval pipeline",
      "GPA, CGPA, carryovers and degree classification",
      "Transcripts and the Official Grade Report",
      "Broadsheets exported to Excel",
    ],
  },
  {
    title: "Administration",
    items: [
      "Faculty, department, programme and course structure",
      "Bulk enrolment and onboarding from CSV or XLSX",
      "A role for every position, lecturer through Senate",
      "Lecturer-to-course assignment, per session and semester",
    ],
  },
  {
    title: "Communication & access",
    items: [
      "Email, SMS and WhatsApp on the events that matter",
      "GPA checks over plain SMS and USSD, no data needed",
      "Mobile-first screens that hold up on a 3G connection",
    ],
  },
  {
    title: "Accreditation & integrity",
    items: [
      "The NUC auditor vault: scoped, expiring, read-only",
      "An append-only audit trail on every score and approval",
      "Database-level immutability on ratified results",
      "External examiner records per programme and term",
    ],
  },
];

const PRIMARY_FEATURES = [
  {
    kicker: "Results integrity",
    title: "A results pipeline that cannot be quietly edited.",
    body: "Every sheet moves lecturer → HOD → Dean → Senate, and no step can be skipped. Scores are append-only: a correction becomes a new row that supersedes the old one, never an overwrite. Database triggers enforce it below the application, so no code path and no manual query can rewrite a ratified result.",
    points: [
      "Four-stage approval chain",
      "Append-only score history",
      "Database-level immutability",
    ],
  },
  {
    kicker: "Resilient proctored CBT",
    title: "Exams that survive the power going out.",
    body: "Timing is server-authoritative, so a dropped connection costs a student nothing. They resume the same paper, in the same order, against the original deadline, and a background sweep submits and grades anything left open. Proctoring signals raise flags for a human to review — never an automatic penalty.",
    points: [
      "Resilient resume and auto-submit",
      "Lockdown and webcam signals",
      "Flags are review-only",
    ],
  },
  {
    kicker: "NUC accreditation vault",
    title: "Hand auditors a key, not your database.",
    body: "Mint a read-only token scoped to specific programmes and sessions, with an expiry, and revoke it the moment the visit ends. The auditor is never a user of your system, cannot reach a single write endpoint, and every request they make is appended to an access log.",
    points: ["Scoped, expiring, revocable", "Read-only by construction", "Every access logged"],
  },
];

const LOCAL = [
  {
    title: "Offline-tolerant exams",
    body: "A student who loses power mid-paper resumes exactly where they were. Nothing about an attempt depends on staying connected.",
  },
  {
    title: "Built for poor networks",
    body: "Screens are light and work over 3G. When there is no data at all, a student can still check their GPA by SMS or USSD.",
  },
  {
    title: "Priced in naira",
    body: "Billed locally, in local currency, against local payment rails. No dollar invoice, no FX surprise at renewal.",
  },
  {
    title: "Matric numbers, not invented IDs",
    body: "Students are identified by the matric number their institution already issued — on their records, on their results, and on the SMS result check.",
  },
];

export function LandingPage() {
  const { status } = useAuth();
  const authenticated = status === "authenticated";

  return (
    <PublicLayout>
      <section className={styles.hero}>
        <div className={styles.heroInner}>
          <div className={styles.heroCopy}>
            <p className={styles.eyebrow}>Learning Management System</p>
            <h1 className={styles.heroTitle}>
              The complete platform for teaching, assessment, and records.
            </h1>
            <p className={styles.heroSub}>
              Senet is a full LMS for Nigerian universities — course content, lessons, discussions,
              assignments, computer-based testing, gradebook, results, and records. One platform
              from enrollment through convocation, with the integrity and resilience your
              institution requires.
            </p>
            <div className={styles.heroActions}>
              <Link className={styles.primaryCta} to={authenticated ? "/app" : "/login"}>
                {authenticated ? "Go to workspace" : "Sign in"}
              </Link>
              <a className={styles.secondaryCta} href="#platform">
                Explore the platform
              </a>
            </div>
          </div>
          <HeroVisual />
        </div>
      </section>

      <section className={styles.section} id="platform">
        <div className={styles.sectionInner}>
          <p className={styles.sectionTitle}>The platform</p>
          <h2 className={styles.scopeTitle}>One system for the entire academic experience.</h2>
          <p className={styles.scopeLead}>
            Senet replaces the fragmented stack most universities struggle with — student portals,
            learning platforms, CBT vendors, spreadsheets, and records systems. One platform from
            enrollment through convocation, with teaching and learning at the core.
          </p>
          <div className={styles.scopeGrid}>
            {SCOPE.map((group) => (
              <article className={styles.scope} key={group.title}>
                <h3 className={styles.scopeGroupTitle}>{group.title}</h3>
                <ul className={styles.scopeList}>
                  {group.items.map((item) => (
                    <li className={styles.scopeItem} key={item}>
                      {item}
                    </li>
                  ))}
                </ul>
              </article>
            ))}
          </div>
        </div>
      </section>

      <section className={styles.section} id="features">
        <div className={styles.sectionInner}>
          <p className={styles.sectionTitle}>Where Senet is different</p>
          <h2 className={styles.scopeTitle}>Built for Nigerian university realities.</h2>
          <p className={styles.scopeLead}>
            Senet delivers everything you expect from a complete LMS — content delivery,
            assessments, gradebook, discussions — with three strengths that set it apart in the
            Nigerian context.
          </p>
          <div className={styles.primaryGrid}>
            {PRIMARY_FEATURES.map((feature) => (
              <article className={styles.feature} key={feature.kicker}>
                <p className={styles.kicker}>{feature.kicker}</p>
                <h3 className={styles.featureTitle}>{feature.title}</h3>
                <p className={styles.featureBody}>{feature.body}</p>
                <ul className={styles.points}>
                  {feature.points.map((point) => (
                    <li className={styles.point} key={point}>
                      {point}
                    </li>
                  ))}
                </ul>
              </article>
            ))}
          </div>
        </div>
      </section>

      <section className={styles.section} id="about">
        <div className={styles.sectionInner}>
          <h2 className={styles.sectionTitle}>Built for Nigerian universities</h2>
          <p className={styles.sectionLead}>
            Not a foreign platform with a local reseller. The constraints that shape Senet are the
            ones our institutions actually work under.
          </p>
          <div className={styles.localGrid}>
            {LOCAL.map((item) => (
              <article className={styles.local} key={item.title}>
                <h3 className={styles.localTitle}>{item.title}</h3>
                <p className={styles.localBody}>{item.body}</p>
              </article>
            ))}
          </div>
        </div>
      </section>

      <section className={styles.closing}>
        <div className={styles.closingInner}>
          <h2 className={styles.closingTitle}>Already have an account?</h2>
          <p className={styles.closingSub}>
            Sign in to your institution&rsquo;s workspace to continue.
          </p>
          <Link className={styles.primaryCta} to={authenticated ? "/app" : "/login"}>
            {authenticated ? "Go to workspace" : "Sign in"}
          </Link>
        </div>
      </section>
    </PublicLayout>
  );
}
