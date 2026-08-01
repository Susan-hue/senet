import type { ReactElement } from "react";
import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import { AuthProvider } from "./context";
import { useAuth } from "./hooks";
import { FullPageLoader } from "./components";
import {
  ADMIN_ROLES,
  DEAN_ROLES,
  HOD_ROLES,
  LECTURER_ROLES,
  SENATE_ROLES,
  STUDENT_ROLES,
} from "./types";
import type { Role } from "./types";
import {
  AwardIcon,
  BookIcon,
  ClipboardIcon,
  LayersIcon,
  UsersIcon,
} from "./features/admin/adminIcons";
import {
  BoardSheetPage,
  DeanBoardPage,
  ExternalExaminersPage,
  HodBoardPage,
  SenateBoardPage,
} from "./features/board";
import { ScoreSheetPage } from "./features/results";
import { AssessmentsPage, GradeItemPage } from "./features/assessments";
import { MyResultsPage } from "./features/student";
import { LandingPage } from "./features/landing";
import { LearningCoursePage, LearningCoursesPage } from "./features/lms";
import { PrivacyPage, TermsPage } from "./features/legal";
import {
  ForgotPasswordPage,
  LoginPage,
  RegisterPage,
  ResetPasswordPage,
  VerifyEmailPage,
} from "./features/auth";
import {
  AcademicStructurePage,
  AdminLayout,
  AssignmentsPage,
  CoursesPage,
  DashboardPage,
  ForbiddenPage,
  ImportsPage,
  PeoplePage,
} from "./features/admin";

function ProtectedRoute({
  children,
  roles,
}: {
  children: ReactElement;
  roles?: ReadonlyArray<Role>;
}) {
  const { status, user } = useAuth();
  if (status === "loading") return <FullPageLoader />;
  if (status === "unauthenticated") return <Navigate to="/login" replace />;
  if (roles && !(user?.role && roles.includes(user.role))) {
    return <Navigate to="/403" replace />;
  }
  return children;
}

function RoleHome() {
  const { user } = useAuth();
  if (user?.role && ADMIN_ROLES.includes(user.role)) return <Navigate to="/dashboard" replace />;
  if (user?.role === "lecturer") return <Navigate to="/teach/courses" replace />;
  // Each approval stage lands on its own board rather than a shared inbox: the
  // work, the scope and the consequences of a decision differ at every stage.
  if (user?.role && HOD_ROLES.includes(user.role)) return <Navigate to="/board" replace />;
  if (user?.role && DEAN_ROLES.includes(user.role)) return <Navigate to="/faculty" replace />;
  if (user?.role && SENATE_ROLES.includes(user.role)) return <Navigate to="/senate" replace />;
  if (user?.role && STUDENT_ROLES.includes(user.role)) {
    return <Navigate to="/me/courses" replace />;
  }
  return <Navigate to="/403" replace />;
}

const LECTURER_NAV = [
  { to: "/teach/courses", label: "My Courses", Icon: BookIcon, end: true },
  { to: "/teach/assessments", label: "Assessments", Icon: ClipboardIcon },
];

const STUDENT_NAV = [
  { to: "/me/courses", label: "My Courses", Icon: BookIcon, end: true },
  { to: "/me/results", label: "My Results", Icon: AwardIcon },
];

const HOD_NAV = [{ to: "/board", label: "Departmental Board", Icon: ClipboardIcon, end: true }];

const DEAN_NAV = [
  { to: "/faculty", label: "Faculty Board", Icon: ClipboardIcon, end: true },
  { to: "/faculty/external-examiners", label: "External Examiners", Icon: UsersIcon },
];

const SENATE_NAV = [{ to: "/senate", label: "Senate Ratification", Icon: LayersIcon, end: true }];

function GuestRoute({ children }: { children: ReactElement }) {
  const { status } = useAuth();
  if (status === "loading") return <FullPageLoader />;
  if (status === "authenticated") return <Navigate to="/app" replace />;
  return children;
}

function AppRoutes() {
  return (
    <Routes>
      {/* Public front door. "/app" is the signed-in entry point that sends each
          role to its own workspace. */}
      <Route path="/" element={<LandingPage />} />
      <Route path="/privacy" element={<PrivacyPage />} />
      <Route path="/terms" element={<TermsPage />} />

      <Route
        path="/app"
        element={
          <ProtectedRoute>
            <RoleHome />
          </ProtectedRoute>
        }
      />

      <Route
        element={
          <ProtectedRoute roles={LECTURER_ROLES}>
            <AdminLayout nav={LECTURER_NAV} brandSub="Lecturer Workspace" rolePill="Lecturer" />
          </ProtectedRoute>
        }
      >
        <Route path="/teach" element={<LearningCoursesPage role="lecturer" />} />
        <Route path="/teach/courses" element={<LearningCoursesPage role="lecturer" />} />
        <Route path="/teach/courses/:courseId" element={<LearningCoursePage role="lecturer" />} />
        <Route path="/teach/sheet" element={<ScoreSheetPage />} />
        <Route path="/teach/assessments" element={<AssessmentsPage />} />
        <Route path="/teach/assessments/grade" element={<GradeItemPage />} />
      </Route>

      <Route
        element={
          <ProtectedRoute roles={STUDENT_ROLES}>
            <AdminLayout nav={STUDENT_NAV} brandSub="Student Portal" rolePill="Student" />
          </ProtectedRoute>
        }
      >
        <Route path="/me/courses" element={<LearningCoursesPage role="student" />} />
        <Route path="/me/courses/:courseId" element={<LearningCoursePage role="student" />} />
        <Route path="/me/results" element={<MyResultsPage />} />
      </Route>

      {/* The approval chain. Each board is gated to the single role that owns
          its stage — the API enforces the same split on every transition. */}
      <Route
        element={
          <ProtectedRoute roles={HOD_ROLES}>
            <AdminLayout nav={HOD_NAV} brandSub="Departmental Board" rolePill="HOD" />
          </ProtectedRoute>
        }
      >
        <Route path="/board" element={<HodBoardPage />} />
        <Route path="/board/sheet/:resultId" element={<BoardSheetPage board="hod" />} />
      </Route>

      <Route
        element={
          <ProtectedRoute roles={DEAN_ROLES}>
            <AdminLayout nav={DEAN_NAV} brandSub="Faculty Board" rolePill="Dean" />
          </ProtectedRoute>
        }
      >
        <Route path="/faculty" element={<DeanBoardPage />} />
        <Route path="/faculty/sheet/:resultId" element={<BoardSheetPage board="dean" />} />
        <Route path="/faculty/external-examiners" element={<ExternalExaminersPage />} />
      </Route>

      <Route
        element={
          <ProtectedRoute roles={SENATE_ROLES}>
            <AdminLayout nav={SENATE_NAV} brandSub="Senate" rolePill="Senate" />
          </ProtectedRoute>
        }
      >
        <Route path="/senate" element={<SenateBoardPage />} />
        <Route path="/senate/sheet/:resultId" element={<BoardSheetPage board="senate" />} />
      </Route>

      <Route
        element={
          <ProtectedRoute roles={ADMIN_ROLES}>
            <AdminLayout />
          </ProtectedRoute>
        }
      >
        <Route path="/dashboard" element={<DashboardPage />} />
        <Route path="/academic-structure" element={<AcademicStructurePage />} />
        <Route path="/courses" element={<CoursesPage />} />
        <Route path="/people" element={<PeoplePage />} />
        <Route path="/assignments" element={<AssignmentsPage />} />
        <Route path="/imports" element={<ImportsPage />} />
      </Route>

      <Route
        path="/403"
        element={
          <ProtectedRoute>
            <ForbiddenPage />
          </ProtectedRoute>
        }
      />

      <Route
        path="/login"
        element={
          <GuestRoute>
            <LoginPage />
          </GuestRoute>
        }
      />
      <Route
        path="/register"
        element={
          <GuestRoute>
            <RegisterPage />
          </GuestRoute>
        }
      />
      <Route path="/verify-email" element={<VerifyEmailPage />} />
      <Route path="/forgot-password" element={<ForgotPasswordPage />} />
      <Route path="/reset-password" element={<ResetPasswordPage />} />
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}

export default function App() {
  return (
    <AuthProvider>
      <BrowserRouter>
        <AppRoutes />
      </BrowserRouter>
    </AuthProvider>
  );
}
