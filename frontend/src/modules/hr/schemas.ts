import { z } from "zod";

/** Mirrors app/modules/hr/schemas.py::EmployeeCreateRequest (Spec 14.6) —
 * client-side validation is instant feedback only; the server validates
 * again regardless (never a security control). */
export const employeeFormSchema = z.object({
  first_name: z.string().trim().min(1, "First name is required"),
  last_name: z.string().trim().optional(),
  email: z.email("Enter a valid email address"),
  personal_email: z.union([z.email("Enter a valid email address"), z.literal("")]).optional(),
  phone: z.string().trim().optional(),
  department_id: z.string().optional(),
  position: z.string().trim().optional(),
  level: z.string().trim().optional(),
  employment_type: z.enum(["full_time", "part_time", "contract", "intern"]),
  hire_date: z.string().min(1, "Hire date is required"),
  probation_end_date: z.string().optional(),
  notice_period_days: z.coerce.number().int().min(0).optional(),
});

export type EmployeeFormValues = z.infer<typeof employeeFormSchema>;

/** Mirrors DepartmentCreateRequest/DepartmentUpdateRequest. */
export const departmentFormSchema = z.object({
  name: z.string().trim().min(1, "Name is required"),
  description: z.string().trim().optional(),
});

export type DepartmentFormValues = z.infer<typeof departmentFormSchema>;
