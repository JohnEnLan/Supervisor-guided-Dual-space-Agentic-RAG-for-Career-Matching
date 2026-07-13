import { describe, expect, it } from "vitest";

import { resumeFileError } from "./NewSessionPage";

describe("resumeFileError", () => {
  it("accepts the three supported resume formats", () => {
    expect(resumeFileError(new File(["x"], "resume.pdf"))).toBeNull();
    expect(resumeFileError(new File(["x"], "resume.docx"))).toBeNull();
    expect(resumeFileError(new File(["x"], "resume.txt"))).toBeNull();
  });

  it("rejects unsupported files before upload", () => {
    expect(resumeFileError(new File(["x"], "resume.png"))).toContain("PDF、DOCX 或 TXT");
  });
});
