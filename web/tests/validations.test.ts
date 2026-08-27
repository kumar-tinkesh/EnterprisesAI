import { describe, expect, it } from "vitest";

import {
  dashboardPathForRole,
  roleForDashboard,
  loginSchema,
  signupSchema,
} from "@/lib/validations";

describe("dashboardPathForRole", () => {
  it("maps each role to its own dashboard", () => {
    expect(dashboardPathForRole("vendor_admin")).toBe("/vendor");
    expect(dashboardPathForRole("tenant_admin")).toBe("/tenant");
    expect(dashboardPathForRole("tenant_user")).toBe("/user");
  });
});

describe("roleForDashboard", () => {
  it("inverts the mapping", () => {
    expect(roleForDashboard("/vendor")).toBe("vendor_admin");
    expect(roleForDashboard("/tenant")).toBe("tenant_admin");
    expect(roleForDashboard("/user")).toBe("tenant_user");
  });
});

describe("schemas", () => {
  it("rejects short passwords on signup", () => {
    const r = signupSchema.safeParse({
      email: "a@b.com",
      password: "short",
      confirmPassword: "short",
      fullName: "A",
      role: "tenant_user",
      tenantName: "T",
    });
    expect(r.success).toBe(false);
  });

  it("requires matching confirm password", () => {
    const r = signupSchema.safeParse({
      email: "a@b.com",
      password: "longenough",
      confirmPassword: "different",
      fullName: "A",
      role: "tenant_user",
      tenantName: "T",
    });
    expect(r.success).toBe(false);
  });

  it("accepts a valid login payload", () => {
    const r = loginSchema.safeParse({
      email: "a@b.com",
      password: "whatever",
    });
    expect(r.success).toBe(true);
  });
});