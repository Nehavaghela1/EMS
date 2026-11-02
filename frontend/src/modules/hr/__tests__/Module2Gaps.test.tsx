import { describe, it } from "vitest";

describe("2.5 Employee documents - frontend gaps", () => {
  it.todo("GAP: employee documents screen lists an employee's files (fetchEmployeeDocuments is not used by any screen)");
  it.todo("GAP: employee documents screen uploads a File and shows the new row");
  it.todo("GAP: employee documents screen has a working download link");
  it.todo("GAP: employee documents screen shows an error for a wrong file type or an oversized file");
});

describe("2.6 Resignation, termination & FnF - frontend gaps", () => {
  it.todo("GAP: employee sees a withdraw-resignation button while the resignation is pending");
  it.todo("GAP: approver sees a clearance queue of employees waiting for their sign-off");
  it.todo("GAP: a manager sees a limited exit view with no salary or FnF numbers");
  it.todo("GAP: an 'exit scheduled' status badge is shown for an approved resignation before the last working day");
  it.todo("GAP: separate reason, notes and remark fields are available on the exit forms");
  it.todo("GAP: settings screen to set notice-period defaults");
  it.todo("GAP: an employee cannot open their own FnF statement after exit");
});

describe("Identity screens used by module 2 - frontend gaps", () => {
  it.todo("GAP: forgot/reset password screens have a company code field");
  it.todo("GAP: country can be edited on the locations screen");
  it.todo("GAP: roles screen to view and change user roles");
  it.todo("GAP: head office active toggle on the locations screen");
});
