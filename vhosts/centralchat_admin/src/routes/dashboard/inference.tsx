import { createFileRoute, redirect } from "@tanstack/react-router";

export const Route = createFileRoute("/dashboard/inference")({
  beforeLoad: () => {
    throw redirect({ to: "/dashboard/settings/inference" });
  },
});
