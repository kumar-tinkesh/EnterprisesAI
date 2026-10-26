import { describe, expect, it } from "vitest";

import { buildCron, describeSchedule, parseCron } from "@/lib/builder/schedule";

describe("schedule presets", () => {
  it("round-trips the shapes the picker offers", () => {
    for (const cron of ["0 9 * * *", "30 18 * * 1-5", "15 8 * * 1", "0 7 1 * *", "0 */3 * * *"]) {
      const p = parseCron(cron);
      expect(p.repeat).not.toBe("custom");
      expect(buildCron(p)).toBe(cron);
    }
    expect(parseCron("30 18 * * 1-5")).toMatchObject({ repeat: "weekdays", time: "18:30" });
  });

  it("keeps anything else as a custom expression", () => {
    for (const cron of ["*/10 * * * *", "0 9 * * 1,3", "0 9 31 * *", "nonsense"]) {
      const p = parseCron(cron);
      expect(p.repeat).toBe("custom");
      expect(buildCron(p)).toBe(cron);
    }
  });

  it("builds from picker values, clamped", () => {
    const base = parseCron("0 9 * * *");
    expect(buildCron({ ...base, repeat: "weekly", weekday: 5, time: "17:45" })).toBe("45 17 * * 5");
    expect(buildCron({ ...base, repeat: "monthly", day: 31 })).toBe("0 9 28 * *");
    expect(buildCron({ ...base, repeat: "hours", every: 0 })).toBe("0 */1 * * *");
  });

  it("summarises a trigger for the canvas", () => {
    expect(describeSchedule({ cron: "0 9 * * 1-5", timezone: "Asia/Kolkata" })).toBe("Weekdays 09:00 · Asia/Kolkata");
    expect(describeSchedule({ cron: "0 9 * * 1-5", enabled: false })).toBe("Paused");
    expect(describeSchedule(null)).toBe("Not scheduled yet");
  });
});
