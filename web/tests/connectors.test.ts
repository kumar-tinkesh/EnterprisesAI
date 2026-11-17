import { describe, expect, it } from "vitest";

import { appLabel } from "@/lib/connectors";

describe("appLabel", () => {
  it("gives known apps their proper name and what they do, whatever the admin typed", () => {
    expect(appLabel("gmail", "gmail server")).toEqual({ title: "Gmail", blurb: "Read, search and draft emails" });
    expect(appLabel("Google Calander", "google calander server").title).toBe("Google Calendar");
    expect(appLabel("linkdin", "linkdin server").title).toBe("LinkedIn");
    expect(appLabel("CLIEF", "CLIEF server").title).toBe("GLEIF");
    expect(appLabel("GLIEF").title).toBe("GLEIF");
    expect(appLabel("Atlasian").title).toBe("Atlassian");
    expect(appLabel("jobspy", "jobspy server").title).toBe("JobSpy");
    expect(appLabel("startup job", "startup job server").title).toBe("Startup Jobs");
    expect(appLabel("web search", "web server").title).toBe("Web search");
  });

  it("tidies an unknown one and keeps a description only when it says more than the name", () => {
    expect(appLabel("acme crm server", "acme crm server")).toEqual({ title: "Acme crm", blurb: "" });
    expect(appLabel("acme crm", "Customers and deals")).toEqual({ title: "Acme crm", blurb: "Customers and deals" });
  });
});
