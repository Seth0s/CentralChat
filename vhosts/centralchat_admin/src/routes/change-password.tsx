import { createFileRoute } from "@tanstack/react-router";
import { ChangePasswordPage } from "@/components/auth/ChangePasswordPage";

export const Route = createFileRoute("/change-password")({
  component: ChangePasswordPage,
});
