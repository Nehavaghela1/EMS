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
export const registerCompanySchema = z
  .object({
    company_name: z.string().trim().min(1, "Company name is required"),
    company_email: z.string().trim().email("Enter a valid email address"),
    subdomain: z
      .string()
      .trim()
      .min(2, "Subdomain must be at least 2 characters")
      .max(63, "Subdomain must be at most 63 characters")
      .regex(/^[a-z0-9-]+$/, "Subdomain can only contain lowercase letters, numbers, and hyphens")
      .refine((v) => !v.startsWith("-") && !v.endsWith("-"), "Subdomain cannot start or end with a hyphen")
      .optional()
      .or(z.literal("")),
    company_size: z.string().trim().min(1, "Please select your company size"),
    industry: z.string().trim().optional(),
    phone: z
      .string()
      .trim()
      .regex(/^(\+?[0-9\s-]{7,15})?$/, "Enter a valid international phone number (e.g. +91 9876543210)")
      .optional()
      .or(z.literal("")),
    password: passwordPolicySchema,
    confirm_password: z.string().min(1, "Please confirm your password"),
  })
  .refine((data) => data.password === data.confirm_password, {
    message: "Passwords do not match",
    path: ["confirm_password"],
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

/** Mirrors ChangePasswordRequest (route 6, the settings page). */
export const changePasswordSchema = z.object({
  current_password: z.string().min(1, "Enter your current password"),
  new_password: passwordPolicySchema,
});

export type ChangePasswordValues = z.infer<typeof changePasswordSchema>;
