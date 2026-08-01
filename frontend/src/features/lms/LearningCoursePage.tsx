import { useState } from "react";
import { useParams, useSearchParams } from "react-router-dom";
import { EmptyState, ErrorState, LoadingState } from "../../components/admin";
import { useAuth } from "../../hooks";
import { getCourse } from "../../services/accounts";
import { API_BASE_URL, apiRequest } from "../../services/api";
import type { Course, Page } from "../../types";
import { useAsyncData } from "../admin/useAsyncData";
import { PageHeader } from "../admin/ui";
import { BookIcon, LayersIcon, LinkIcon, UploadIcon, UsersIcon } from "../admin/adminIcons";
import adminStyles from "../admin/admin.module.css";
import styles from "./lms.module.css";

type ContentKind = "file" | "page" | "link" | "video";

interface ModuleRow {
  id: string;
  title: string;
  description: string;
  is_published: boolean;
  item_count: number;
  position: number;
  course_code: string;
  course_title: string;
}

interface ContentItemRow {
  id: string;
  title: string;
  description: string;
  kind: ContentKind;
  is_published: boolean;
  file_url: string | null;
  original_filename: string;
  url: string;
  body: string;
  viewed?: boolean;
  module_title: string;
}

interface AnnouncementRow {
  id: string;
  title: string;
  body: string;
  is_pinned: boolean;
  author_name: string;
  course_code: string;
  course_title: string;
  created_at: string;
}

interface ThreadRow {
  id: string;
  title: string;
  body: string;
  is_pinned: boolean;
  reply_count: number;
  author_name: string;
  author_role: string;
  created_at: string;
}

interface ModuleWithItems extends ModuleRow {
  items: ContentItemRow[];
}

function contentKindLabel(kind: ContentKind) {
  switch (kind) {
    case "file":
      return "File";
    case "page":
      return "Lesson";
    case "link":
      return "Link";
    case "video":
      return "Video";
    default:
      return "Material";
  }
}

export function LearningCoursePage({ role }: { role: "lecturer" | "student" }) {
  const { courseId } = useParams();
  const [searchParams] = useSearchParams();
  const { accessToken } = useAuth();
  const token = accessToken ?? "";
  const sessionId = searchParams.get("session") ?? "";
  const semesterId = searchParams.get("semester") ?? "";
  const [tab, setTab] = useState<"content" | "announcements" | "discussions">("content");
  const [moduleTitle, setModuleTitle] = useState("");
  const [moduleDescription, setModuleDescription] = useState("");
  const [announcementTitle, setAnnouncementTitle] = useState("");
  const [announcementBody, setAnnouncementBody] = useState("");
  const [threadTitle, setThreadTitle] = useState("");
  const [threadBody, setThreadBody] = useState("");
  const [replyBody, setReplyBody] = useState<Record<string, string>>({});
  const [itemTitle, setItemTitle] = useState("");
  const [itemDescription, setItemDescription] = useState("");
  const [itemKind, setItemKind] = useState<ContentKind>("page");
  const [itemUrl, setItemUrl] = useState("");
  const [itemBody, setItemBody] = useState("");
  const [selectedModuleId, setSelectedModuleId] = useState("");
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [statusMessage, setStatusMessage] = useState<string | null>(null);

  const courseData = useAsyncData(() => (courseId ? getCourse(courseId, token) : Promise.resolve(null)), [token, courseId]);
  const course = courseData.data as Course | null;

  const modulesData = useAsyncData(async () => {
    if (!courseId || !sessionId || !semesterId || !token) return [] as ModuleWithItems[];
    const moduleResponse = await apiRequest<Page<ModuleRow>>(
      `/api/v1/content/modules?course=${courseId}&session=${sessionId}&semester=${semesterId}`,
      { token },
    );
    const modules = moduleResponse.data?.results ?? [];
    return Promise.all(
      modules.map(async (module) => {
        const itemsResponse = await apiRequest<Page<ContentItemRow>>(`/api/v1/content/modules/${module.id}/items`, { token });
        return {
          ...module,
          items: itemsResponse.data?.results ?? [],
        } satisfies ModuleWithItems;
      }),
    );
  }, [token, courseId, sessionId, semesterId]);

  const modules = (modulesData.data ?? []) as ModuleWithItems[];

  const announcementsData = useAsyncData(async () => {
    if (!courseId || !sessionId || !semesterId || !token) return [] as AnnouncementRow[];
    const response = await apiRequest<Page<AnnouncementRow>>(
      `/api/v1/announcements/?course=${courseId}&session=${sessionId}&semester=${semesterId}`,
      { token },
    );
    return response.data?.results ?? [];
  }, [token, courseId, sessionId, semesterId]);
  const announcements = (announcementsData.data ?? []) as AnnouncementRow[];

  const threadsData = useAsyncData(async () => {
    if (!courseId || !sessionId || !semesterId || !token) return [] as ThreadRow[];
    const response = await apiRequest<Page<ThreadRow>>(
      `/api/v1/discussions/threads?course=${courseId}&session=${sessionId}&semester=${semesterId}`,
      { token },
    );
    return response.data?.results ?? [];
  }, [token, courseId, sessionId, semesterId]);
  const threads = (threadsData.data ?? []) as ThreadRow[];

  const isLecturer = role === "lecturer";

  async function handleCreateModule() {
    if (!courseId || !token || !moduleTitle.trim() || !sessionId || !semesterId) return;
    setIsSubmitting(true);
    setStatusMessage(null);
    try {
      await apiRequest<ModuleRow>("/api/v1/content/modules", {
        method: "POST",
        body: {
          course: courseId,
          session: sessionId,
          semester: semesterId,
          title: moduleTitle,
          description: moduleDescription,
          is_published: true,
        },
        token,
      });
      setModuleTitle("");
      setModuleDescription("");
      setStatusMessage("Module created.");
      await modulesData.reload();
    } catch (error) {
      setStatusMessage(error instanceof Error ? error.message : "Could not create module.");
    } finally {
      setIsSubmitting(false);
    }
  }

  async function handleCreateAnnouncement() {
    if (!courseId || !token || !announcementTitle.trim() || !announcementBody.trim() || !sessionId || !semesterId) return;
    setIsSubmitting(true);
    setStatusMessage(null);
    try {
      await apiRequest<AnnouncementRow>("/api/v1/announcements/", {
        method: "POST",
        body: {
          course: courseId,
          session: sessionId,
          semester: semesterId,
          title: announcementTitle,
          body: announcementBody,
          is_pinned: true,
        },
        token,
      });
      setAnnouncementTitle("");
      setAnnouncementBody("");
      setStatusMessage("Announcement posted.");
      await announcementsData.reload();
    } catch (error) {
      setStatusMessage(error instanceof Error ? error.message : "Could not post announcement.");
    } finally {
      setIsSubmitting(false);
    }
  }

  async function handleCreateThread() {
    if (!courseId || !token || !threadTitle.trim() || !threadBody.trim() || !sessionId || !semesterId) return;
    setIsSubmitting(true);
    setStatusMessage(null);
    try {
      await apiRequest<ThreadRow>("/api/v1/discussions/threads", {
        method: "POST",
        body: {
          course: courseId,
          session: sessionId,
          semester: semesterId,
          title: threadTitle,
          body: threadBody,
          is_pinned: false,
        },
        token,
      });
      setThreadTitle("");
      setThreadBody("");
      setStatusMessage("Thread created.");
      await threadsData.reload();
    } catch (error) {
      setStatusMessage(error instanceof Error ? error.message : "Could not post thread.");
    } finally {
      setIsSubmitting(false);
    }
  }

  async function handleCreateReply(threadId: string) {
    if (!token || !replyBody[threadId]?.trim()) return;
    setIsSubmitting(true);
    setStatusMessage(null);
    try {
      await apiRequest<{ id: string }>(`/api/v1/discussions/threads/${threadId}/replies`, {
        method: "POST",
        body: { body: replyBody[threadId] },
        token,
      });
      setReplyBody((prev) => ({ ...prev, [threadId]: "" }));
      setStatusMessage("Reply posted.");
      await threadsData.reload();
    } catch (error) {
      setStatusMessage(error instanceof Error ? error.message : "Could not post reply.");
    } finally {
      setIsSubmitting(false);
    }
  }

  async function handleCreateItem() {
    if (!token || !courseId || !selectedModuleId || !itemTitle.trim()) return;
    setIsSubmitting(true);
    setStatusMessage(null);
    try {
      const form = new FormData();
      form.append("title", itemTitle);
      form.append("description", itemDescription);
      form.append("kind", itemKind);
      form.append("is_published", itemKind === "page" ? "true" : "false");
      if (itemKind === "page") {
        form.append("body", itemBody);
      } else if (itemKind === "link" || itemKind === "video") {
        form.append("url", itemUrl);
      } else if (selectedFile) {
        form.append("file", selectedFile);
      }

      const response = await fetch(`${API_BASE_URL}/api/v1/content/modules/${selectedModuleId}/items`, {
        method: "POST",
        headers: { Authorization: `Bearer ${token}` },
        body: form,
        credentials: "include",
      });
      let envelope: { message?: string } | null = null;
      try {
        envelope = await response.json();
      } catch {
        envelope = null;
      }
      if (!response.ok || envelope?.message === undefined) {
        throw new Error(envelope?.message ?? "Could not create the content item.");
      }
      setItemTitle("");
      setItemDescription("");
      setItemUrl("");
      setItemBody("");
      setSelectedFile(null);
      setStatusMessage("Content item created.");
      await modulesData.reload();
    } catch (error) {
      setStatusMessage(error instanceof Error ? error.message : "Could not create content item.");
    } finally {
      setIsSubmitting(false);
    }
  }

  async function handleOpenItem(itemId: string) {
    if (!token) return;
    try {
      await apiRequest<{ id: string }>(`/api/v1/content/items/${itemId}/view`, {
        method: "POST",
        token,
      });
      setStatusMessage("Read receipt recorded.");
      await modulesData.reload();
    } catch {
      setStatusMessage("Unable to record the view right now.");
    }
  }

  return (
    <div className={adminStyles.page}>
      <PageHeader
        title={course ? `${course.code} · ${course.title}` : "Course learning area"}
        subtitle={course ? "Modules, announcements and discussions for this course." : "Loading the course workspace…"}
      />

      {(!sessionId || !semesterId) && course ? (
        <EmptyState
          title="Course context is missing"
          hint="Open this course from My Courses so the active session and semester are attached to the route."
          icon={<BookIcon size={22} />}
        />
      ) : null}

      {(courseData.loading || modulesData.loading || announcementsData.loading || threadsData.loading) && !course ? (
        <LoadingState label="Loading learning area…" />
      ) : null}
      {courseData.error ? <ErrorState message={courseData.error} onRetry={courseData.reload} /> : null}

      {!course && !courseData.loading ? (
        <EmptyState
          title="Course not found"
          hint="You may not have access to this course or it does not exist for your current term."
          icon={<BookIcon size={22} />}
        />
      ) : null}

      {course ? (
        <>
          <div className={styles.toolbar}>
            <div className={styles.tabs} role="tablist" aria-label="Course area">
              {[
                ["content", "Content"],
                ["announcements", "Announcements"],
                ["discussions", "Discussions"],
              ].map(([key, label]) => (
                <button
                  key={key}
                  type="button"
                  className={[styles.tab, tab === key ? styles.tabActive : ""].join(" ")}
                  onClick={() => setTab(key as typeof tab)}
                >
                  {label}
                </button>
              ))}
            </div>
            {statusMessage ? <p className={styles.status}>{statusMessage}</p> : null}
          </div>

          {tab === "content" ? (
            <div className={styles.grid}>
              <section className={styles.panel}>
                <div className={styles.panelHead}>
                  <h2>Learning content</h2>
                  {isLecturer ? <span className={styles.metaBadge}>Manage</span> : <span className={styles.metaBadge}>Browse</span>}
                </div>
                {isLecturer ? (
                  <div className={styles.formCard}>
                    <h3>Create module</h3>
                    <input
                      className={styles.input}
                      placeholder="Module title"
                      value={moduleTitle}
                      onChange={(event) => setModuleTitle(event.target.value)}
                    />
                    <textarea
                      className={styles.textarea}
                      placeholder="Short description"
                      value={moduleDescription}
                      onChange={(event) => setModuleDescription(event.target.value)}
                    />
                    <button type="button" className={styles.primaryButton} onClick={() => void handleCreateModule()} disabled={isSubmitting}>
                      {isSubmitting ? "Saving…" : "Create module"}
                    </button>
                  </div>
                ) : null}
                {modules.length === 0 ? (
                  <EmptyState
                    title="No published content yet"
                    hint="The lecturer has not published learning material for this course yet."
                    icon={<LayersIcon size={22} />}
                  />
                ) : (
                  <div className={styles.list}>
                    {modules.map((module) => (
                      <div key={module.id} className={styles.card}>
                        <div className={styles.cardHead}>
                          <strong>{module.title}</strong>
                          <span>{module.item_count} items</span>
                        </div>
                        <p>{module.description || "No module description yet."}</p>
                        <div className={styles.list}>
                          {module.items.length === 0 ? (
                            <p>No items in this module yet.</p>
                          ) : (
                            module.items.map((item) => (
                              <div key={item.id} className={styles.card}>
                                <div className={styles.cardHead}>
                                  <strong>{item.title}</strong>
                                  <span>{contentKindLabel(item.kind)}</span>
                                </div>
                                <p>{item.description || item.body || "No summary yet."}</p>
                                {item.file_url ? (
                                  <a href={item.file_url} target="_blank" rel="noreferrer">
                                    Download material
                                  </a>
                                ) : null}
                                {item.url ? (
                                  <a href={item.url} target="_blank" rel="noreferrer">
                                    Open link
                                  </a>
                                ) : null}
                                {!isLecturer ? (
                                  <button type="button" className={styles.secondaryButton} onClick={() => void handleOpenItem(item.id)}>
                                    Mark as read
                                  </button>
                                ) : null}
                              </div>
                            ))
                          )}
                        </div>
                      </div>
                    ))}
                  </div>
                )}
              </section>

              <section className={styles.panel}>
                <div className={styles.panelHead}>
                  <h2>Materials</h2>
                  {isLecturer ? <span className={styles.metaBadge}>Create</span> : null}
                </div>
                {isLecturer ? (
                  <div className={styles.formCard}>
                    <h3>Add lesson item</h3>
                    <select
                      className={styles.select}
                      value={selectedModuleId}
                      onChange={(event) => setSelectedModuleId(event.target.value)}
                    >
                      <option value="">Select a module</option>
                      {modules.map((module) => (
                        <option key={module.id} value={module.id}>
                          {module.title}
                        </option>
                      ))}
                    </select>
                    <input
                      className={styles.input}
                      placeholder="Item title"
                      value={itemTitle}
                      onChange={(event) => setItemTitle(event.target.value)}
                    />
                    <textarea
                      className={styles.textarea}
                      placeholder="Describe the lesson"
                      value={itemDescription}
                      onChange={(event) => setItemDescription(event.target.value)}
                    />
                    <select className={styles.select} value={itemKind} onChange={(event) => setItemKind(event.target.value as ContentKind)}>
                      <option value="page">Lesson</option>
                      <option value="file">File</option>
                      <option value="link">Link</option>
                      <option value="video">Video</option>
                    </select>
                    {itemKind === "page" ? (
                      <textarea
                        className={styles.textarea}
                        placeholder="Lesson body"
                        value={itemBody}
                        onChange={(event) => setItemBody(event.target.value)}
                      />
                    ) : null}
                    {(itemKind === "link" || itemKind === "video") ? (
                      <input
                        className={styles.input}
                        placeholder="Link or embed URL"
                        value={itemUrl}
                        onChange={(event) => setItemUrl(event.target.value)}
                      />
                    ) : null}
                    {itemKind === "file" ? (
                      <input
                        className={styles.input}
                        type="file"
                        onChange={(event) => setSelectedFile(event.target.files?.[0] ?? null)}
                      />
                    ) : null}
                    <button type="button" className={styles.primaryButton} onClick={() => void handleCreateItem()} disabled={isSubmitting}>
                      Save content item
                    </button>
                  </div>
                ) : null}
                {modules.every((module) => module.items.length === 0) ? (
                  <EmptyState
                    title="No lesson items yet"
                    hint="Publishing content for this course will make it appear here."
                    icon={<UploadIcon size={22} />}
                  />
                ) : (
                  <div className={styles.list}>
                    {modules.flatMap((module) =>
                      module.items.map((item) => (
                        <div key={item.id} className={styles.card}>
                          <div className={styles.cardHead}>
                            <strong>{item.title}</strong>
                            <span>{contentKindLabel(item.kind)}</span>
                          </div>
                          <p>{item.description || item.body || "No summary yet."}</p>
                          {item.file_url ? <a href={item.file_url} target="_blank" rel="noreferrer">Download material</a> : null}
                          {item.url ? <a href={item.url} target="_blank" rel="noreferrer">Open link</a> : null}
                        </div>
                      )),
                    )}
                  </div>
                )}
              </section>
            </div>
          ) : null}

          {tab === "announcements" ? (
            <section className={styles.panel}>
              <div className={styles.panelHead}>
                <h2>Announcements</h2>
                {isLecturer ? <span className={styles.metaBadge}>Post</span> : null}
              </div>
              {isLecturer ? (
                <div className={styles.formCard}>
                  <h3>Post announcement</h3>
                  <input
                    className={styles.input}
                    placeholder="Announcement title"
                    value={announcementTitle}
                    onChange={(event) => setAnnouncementTitle(event.target.value)}
                  />
                  <textarea
                    className={styles.textarea}
                    placeholder="Write the announcement"
                    value={announcementBody}
                    onChange={(event) => setAnnouncementBody(event.target.value)}
                  />
                  <button type="button" className={styles.primaryButton} onClick={() => void handleCreateAnnouncement()} disabled={isSubmitting}>
                    {isSubmitting ? "Posting…" : "Publish announcement"}
                  </button>
                </div>
              ) : null}
              {announcements.length === 0 ? (
                <EmptyState title="No announcements yet" hint="New course updates will show up here." icon={<LinkIcon size={22} />} />
              ) : (
                <div className={styles.list}>
                  {announcements.map((announcement) => (
                    <div key={announcement.id} className={styles.card}>
                      <div className={styles.cardHead}>
                        <strong>{announcement.title}</strong>
                        {announcement.is_pinned ? <span>Pinned</span> : <span>Latest</span>}
                      </div>
                      <p>{announcement.body}</p>
                      <small>Posted by {announcement.author_name}</small>
                    </div>
                  ))}
                </div>
              )}
            </section>
          ) : null}

          {tab === "discussions" ? (
            <section className={styles.panel}>
              <div className={styles.panelHead}>
                <h2>Discussion board</h2>
                <span className={styles.metaBadge}>Course forum</span>
              </div>
              <div className={styles.formCard}>
                <h3>Start a thread</h3>
                <input
                  className={styles.input}
                  placeholder="Thread title"
                  value={threadTitle}
                  onChange={(event) => setThreadTitle(event.target.value)}
                />
                <textarea
                  className={styles.textarea}
                  placeholder="Share a question or update"
                  value={threadBody}
                  onChange={(event) => setThreadBody(event.target.value)}
                />
                <button type="button" className={styles.primaryButton} onClick={() => void handleCreateThread()} disabled={isSubmitting}>
                  {isSubmitting ? "Posting…" : "Start thread"}
                </button>
              </div>
              {threads.length === 0 ? (
                <EmptyState title="No discussion threads yet" hint="Start the first conversation for this course." icon={<UsersIcon size={22} />} />
              ) : (
                <div className={styles.list}>
                  {threads.map((thread) => (
                    <div key={thread.id} className={styles.card}>
                      <div className={styles.cardHead}>
                        <strong>{thread.title}</strong>
                        <span>{thread.reply_count} replies</span>
                      </div>
                      <p>{thread.body}</p>
                      <small>Started by {thread.author_name}</small>
                      <div className={styles.replyBox}>
                        <textarea
                          className={styles.textarea}
                          placeholder="Write a reply"
                          value={replyBody[thread.id] ?? ""}
                          onChange={(event) => setReplyBody((prev) => ({ ...prev, [thread.id]: event.target.value }))}
                        />
                        <button type="button" className={styles.secondaryButton} onClick={() => void handleCreateReply(thread.id)}>
                          Reply
                        </button>
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </section>
          ) : null}
        </>
      ) : null}
    </div>
  );
}
