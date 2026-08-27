"use client";

import { z } from "zod";

/** Role values the backend expects (must match `src/core/roles.py`). */
export const ROLES = {
  vendorAdmin: "vendor_admin",
  tenantAdmin: "tenant_admin",
  tenantUser: "tenant_user",
  soloUser: "solo_user",
} as const;

export type Role = (typeof ROLES)[keyof typeof ROLES];

export const ROLE_LABELS: Record<Role, string> = {
  vendor_admin: "Vendor Admin",
  tenant_admin: "Tenant Admin",
  tenant_user: "Tenant User",
  solo_user: "(Individual)",
};

/** Zod schema shared by the login form. */
export const loginSchema = z.object({
  email: z.string().email("Enter a valid email"),
  password: z.string().min(1, "Password is required"),
});

export type LoginValues = z.infer<typeof loginSchema>;

/** Zod schema shared by the signup form. */
export const signupSchema = z
  .object({
    email: z.string().email("Enter a valid email"),
    password: z.string().min(8, "Password must be at least 8 characters"),
    confirmPassword: z.string(),
    fullName: z.string().min(1, "Full name is required").max(255),
    role: z.nativeEnum(ROLES),
    tenantName: z.string().max(255).optional().default(""),
  })
  .refine((d) => d.password === d.confirmPassword, {
    message: "Passwords do not match",
    path: ["confirmPassword"],
  })
  .refine(
    (d) =>
      d.role === ROLES.vendorAdmin ||
      d.role === ROLES.soloUser ||
      d.tenantName.trim().length > 0,
    {
      message: "Tenant / Organization name is required",
      path: ["tenantName"],
    },
  );

export type SignupValues = z.infer<typeof signupSchema>;

/** The account payload returned by `/auth/login` and `/auth/signup`. */
export interface Account {
  id: string;
  email: string;
  full_name: string;
  role: Role;
  tenant_id: string | null;
}

export interface AuthPayload {
  access_token: string;
  refresh_token: string;
  token_type: string;
  user: Account;
}

/** Map a role to the dashboard path it is allowed to open. */
export function dashboardPathForRole(role: Role): string {
  switch (role) {
    case ROLES.vendorAdmin:
      return "/vendor";
    case ROLES.tenantAdmin:
      return "/tenant";
    default:
      return "/user";
  }
}

/** Map the dashboard segment back to the role it requires. */
export function roleForDashboard(path: string): Role | Role[] {
  if (path === "/vendor") return ROLES.vendorAdmin;
  if (path === "/tenant") return ROLES.tenantAdmin;
  return [ROLES.tenantUser, ROLES.soloUser];
}