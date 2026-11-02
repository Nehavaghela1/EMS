import { describe, it } from "vitest";

describe("3.1 Announcements – Frontend gaps", () => {
  it.todo("GAP: HR/manager create-announcement form with department choice");
  it.todo("GAP: poster and HR-level delete button visible on announcement card");
  it.todo("GAP: delete button hidden for non-poster, non-HR users");
});

describe("3.3 Files & Vault – Frontend gaps", () => {
  it.todo("GAP: vault page for generic files (platform upload, signed-link list)");
  it.todo("GAP: project document upload error message for wrong file type (422)");
  it.todo("GAP: project document upload error message for oversized file (413)");
});

describe("3.4 Global Search – Frontend gaps", () => {
  it.todo("GAP: search results list rendered from GET /search using globalSearch api");
  it.todo("GAP: directory-only hit with url null is not clickable in results list");
});

describe("3.5 Audit Logs – Frontend gaps", () => {
  it.todo("GAP: audit logs page renders list with actor, action and timestamp");
  it.todo("GAP: audit logs page filters by action, actor email and date range");
  it.todo("GAP: audit logs export request button calls requestAuditLogExport");
  it.todo("GAP: audit logs download button calls downloadAuditLogExport after job completes");
});

describe("3.6 Background Jobs – Frontend gaps", () => {
  it.todo("GAP: job progress/failure message shown for audit export job");
});

