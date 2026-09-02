import { z } from "zod";

/** Mirrors app/modules/identity/schemas.py::_validate_password_policy
 * exactly (min length from settings, currently 10; max 128; at least one
 * letter and one digit) — client-side validation is instant feedback
 * only, the server always validates again (Spec 14.6). */
export const passwordPolicySchema = z
  .string()
  .min(10, "Password must be at least 10 characters.")
  .max(128, "Password must be at most 128 characters.")
  .refine((v) => /[A-Za-z]/.test(v), "Password must contain at least one letter.")
  .refine((v) => /[0-9]/.test(v), "Password must contain at least one digit.");

/** Mirrors CompanyRegisterRequest. `country` isn't collected — the
 * backend defaults it to "IN" and no other value is exercised anywhere
 * else in this project yet. */
export const registerCompanySchema = z.object({
  company_name: z.string().trim().min(1, "Company name is required"),
  company_email: z.email("Enter a valid email address"),
  industry: z.string().trim().optional(),
  phone: z.string().trim().optional(),
});

export type RegisterCompanyValues = z.infer<typeof registerCompanySchema>;

/** Mirrors ActivateAccountRequest minus `token`, which comes from the URL
 * (Spec 10.2 route 11), never a form field. */
export const activateAccountSchema = z.object({
  username: z.string().trim().min(3, "Username must be at least 3 characters"),
  password: passwordPolicySchema,
});

export type ActivateAccountValues = z.infer<typeof activateAccountSchema>;

export const forgotPasswordEmailSchema = z.email("Enter a valid email address");

/** Mirrors ResetPasswordRequest minus `email`, carried over from step one
 * rather than re-entered. */
export const resetPasswordSchema = z.object({
  otp: z.string().trim().min(1, "Enter the code we sent you"),
  new_password: passwordPolicySchema,
});

export type ResetPasswordValues = z.infer<typeof resetPasswordSchema>;
