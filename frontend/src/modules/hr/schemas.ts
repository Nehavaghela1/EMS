import { z } from "zod";

/** Mirrors app/modules/hr/schemas.py::EmployeeCreateRequest (Spec 14.6) —
 * client-side validation is instant feedback only; the server validates
 * again regardless (never a security control). */
export const employeeFormSchema = z.object({
  first_name: z
    .string()
    .trim()
    .min(1, "First name is required")
    .max(100, "First name must not exceed 100 characters"),
  last_name: z
    .string()
    .trim()
    .max(100, "Last name must not exceed 100 characters")
    .optional(),
  email: z
    .string()
    .trim()
    .max(255, "Work email must not exceed 255 characters")
    .email("Enter a valid email address"),
  personal_email: z
    .union([
      z
        .string()
        .trim()
        .max(255, "Personal email must not exceed 255 characters")
        .email("Enter a valid email address"),
      z.literal(""),
    ])
    .optional(),
  phone: z
    .string()
    .trim()
    .max(20, "Phone number must not exceed 20 characters")
    .optional(),
  department_id: z.string().trim().optional(),
  location_id: z.string().trim().optional(),
  reporting_manager_id: z.string().trim().optional(),
  position: z
    .string()
    .trim()
    .max(150, "Position must not exceed 150 characters")
    .optional(),
  level: z.enum(["L1", "L2", "L3"]).optional().or(z.literal("")),
  employment_type: z.enum(["full_time", "part_time", "contract", "intern"]),
  hire_date: z.string().min(1, "Hire date is required"),
  probation_end_date: z.string().optional(),
  notice_period_days: z.coerce
    .number()
    .int()
    .min(0, "Notice period must be between 0 and 365 days")
    .max(365, "Notice period must be between 0 and 365 days")
    .optional(),
});

export type EmployeeFormValues = z.infer<typeof employeeFormSchema>;

/** Mirrors DepartmentCreateRequest/DepartmentUpdateRequest. */
export const departmentFormSchema = z.object({
  name: z.string().trim().min(1, "Name is required"),
  description: z.string().trim().optional(),
});

export type DepartmentFormValues = z.infer<typeof departmentFormSchema>;
