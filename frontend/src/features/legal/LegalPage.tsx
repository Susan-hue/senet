import type { ReactNode } from "react";
import { PublicLayout } from "../../components/PublicLayout";
import styles from "./legal.module.css";

export interface LegalSection {
  id?: string;
  heading: string;
  body: ReactNode;
}

/**
 * Shared shell for the policy pages. The draft banner is part of the shell
 * rather than each page's copy, so neither page can ship without it.
 */
export function LegalPage({
  title,
  updated,
  intro,
  sections,
}: {
  title: string;
  updated: string;
  intro: ReactNode;
  sections: LegalSection[];
}) {
  return (
    <PublicLayout>
      <article className={styles.page}>
        <div className={styles.inner}>
          <div className={styles.draft} role="note">
            <span className={styles.draftTag}>Draft</span>
            <p className={styles.draftText}>
              This document is a working draft pending review by qualified legal counsel. It is
              published for transparency and is not a finalised legal agreement. Nothing here should
              be relied on as legal advice or as a binding statement of Senet&rsquo;s obligations.
            </p>
          </div>

          <header className={styles.header}>
            <h1 className={styles.title}>{title}</h1>
            <p className={styles.meta}>Last updated {updated}</p>
          </header>

          <div className={styles.intro}>{intro}</div>

          {sections.map((section, index) => (
            <section className={styles.section} id={section.id} key={section.heading}>
              <h2 className={styles.heading}>
                <span className={styles.number}>{index + 1}.</span> {section.heading}
              </h2>
              <div className={styles.body}>{section.body}</div>
            </section>
          ))}
        </div>
      </article>
    </PublicLayout>
  );
}
