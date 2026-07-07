import type { ReactElement } from "react";
import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import { AuthProvider } from "./context";
import { useAuth } from "./hooks";
import { FullPageLoader } from "./components";
import { ADMIN_ROLES, LECTURER_ROLES } from "./types";
import type { Role } from "./types";
import { BookIcon } from "./features/admin/adminIcons";
import { MyCoursesPage, ScoreSheetPage } from "./features/results";
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
  if (user?.role === "lecturer") return <Navigate to="/teach" replace />;
  return <Navigate to="/403" replace />;
}

const LECTURER_NAV = [{ to: "/teach", label: "My Courses", Icon: BookIcon }];

function GuestRoute({ children }: { children: ReactElement }) {
  const { status } = useAuth();
  if (status === "loading") return <FullPageLoader />;
  if (status === "authenticated") return <Navigate to="/" replace />;
  return children;
}

function AppRoutes() {
  return (
    <Routes>
      <Route
        path="/"
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
        <Route path="/teach" element={<MyCoursesPage />} />
        <Route path="/teach/sheet" element={<ScoreSheetPage />} />
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
