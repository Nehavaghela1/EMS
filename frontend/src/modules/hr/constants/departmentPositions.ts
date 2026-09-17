/**
 * Recommended Standard Positions by Department.
 * If a department is selected, these positions appear in the suggestions dropdown
 * while still allowing custom text entry.
 */
export const DEPARTMENT_POSITIONS: Record<string, string[]> = {
  // Engineering / Technology / IT
  engineering: [
    "Software Engineer / Developer",
    "Senior Software Engineer",
    "Frontend Developer",
    "Backend Developer",
    "Full Stack Developer",
    "Mobile App Developer (iOS / Android)",
    "DevOps Engineer",
    "QA / Automation Test Engineer",
    "Data Engineer",
    "Engineering Manager / Tech Lead",
    "Cloud Solutions Architect",
    "UI/UX Engineer",
  ],
  technology: [
    "Software Engineer / Developer",
    "Senior Software Engineer",
    "Frontend Developer",
    "Backend Developer",
    "Full Stack Developer",
    "Mobile App Developer (iOS / Android)",
    "DevOps Engineer",
    "QA / Automation Test Engineer",
    "Data Engineer",
    "Engineering Manager / Tech Lead",
  ],
  it: [
    "IT Support Specialist",
    "Systems Administrator",
    "Network Engineer",
    "DevOps Engineer",
    "IT Operations Manager",
    "Security Analyst",
  ],

  // Sales / Business Development
  sales: [
    "Sales Executive / Representative",
    "Senior Sales Executive",
    "Business Development Manager (BDM)",
    "Account Manager",
    "Enterprise Account Executive",
    "Inside Sales Specialist",
    "Sales Director / VP of Sales",
  ],

  // Marketing / Growth
  marketing: [
    "Marketing Specialist / Executive",
    "Digital Marketing Manager",
    "Content Strategist / Copywriter",
    "SEO / SEM Specialist",
    "Growth Marketing Manager",
    "Brand Manager",
    "Social Media Manager",
  ],

  // Human Resources / People Operations
  hr: [
    "HR Executive",
    "Senior HR Generalist",
    "Talent Acquisition Specialist / Recruiter",
    "HR Business Partner (HRBP)",
    "Payroll & Compensation Specialist",
    "People Operations Manager",
    "Chief Human Resources Officer (CHRO)",
  ],

  // Finance / Accounting
  finance: [
    "Accountant",
    "Senior Accountant",
    "Financial Analyst",
    "Accounts Payable / Receivable Specialist",
    "Audit & Compliance Manager",
    "Finance Controller",
    "Chief Financial Officer (CFO)",
  ],

  // Design / Creative
  design: [
    "UI/UX Designer",
    "Senior Product Designer",
    "Visual / Graphic Designer",
    "Motion Graphics Designer",
    "Design Lead / Creative Director",
  ],

  // Product Management
  product: [
    "Associate Product Manager",
    "Product Manager",
    "Senior Product Manager",
    "Principal Product Manager",
    "Director of Product",
  ],

  // Operations / Administration
  operations: [
    "Operations Executive",
    "Operations Manager",
    "Office Administrator",
    "Procurement Specialist",
    "Chief Operating Officer (COO)",
  ],

  // Customer Success / Support
  support: [
    "Customer Support Representative",
    "Technical Support Engineer",
    "Customer Success Manager (CSM)",
    "Client Relationship Lead",
  ],
};

/**
 * Fallback common positions across departments
 */
export const DEFAULT_POSITIONS: string[] = [
  "Software Engineer / Developer",
  "Senior Software Engineer",
  "Frontend Developer",
  "Backend Developer",
  "Full Stack Developer",
  "Sales Executive / Representative",
  "Business Development Manager",
  "Marketing Specialist",
  "HR Generalist",
  "Accountant",
  "UI/UX Designer",
  "Operations Executive",
];

/**
 * Helper to format titles to Title Case (e.g., 'prompt engineer' -> 'Prompt Engineer')
 */
export function toTitleCase(str: string): string {
  if (!str) return "";
  return str
    .trim()
    .split(/\s+/)
    .map((word) => {
      // Keep acronyms like QA, UI, UX, IT, VP, HR, SEO, BDM in uppercase if typed
      if (/^(qa|ui|ux|it|vp|hr|seo|sem|bdm|cto|ceo|cfo|coo|cpo)$/i.test(word)) {
        return word.toUpperCase();
      }
      return word.charAt(0).toUpperCase() + word.slice(1).toLowerCase();
    })
    .join(" ");
}

/**
 * Returns the recommended standard positions matching a department name.
 */
export function getPositionsForDepartment(deptName: string | null | undefined): string[] {
  if (!deptName) return DEFAULT_POSITIONS;
  const lower = deptName.toLowerCase();

  for (const [key, positions] of Object.entries(DEPARTMENT_POSITIONS)) {
    if (lower.includes(key)) {
      return positions;
    }
  }

  // Check aliases
  if (lower.includes("tech") || lower.includes("dev") || lower.includes("software") || lower.includes("rd")) {
    return DEPARTMENT_POSITIONS.engineering;
  }
  if (lower.includes("people") || lower.includes("talent") || lower.includes("recruit")) {
    return DEPARTMENT_POSITIONS.hr;
  }
  if (lower.includes("account") || lower.includes("billing")) {
    return DEPARTMENT_POSITIONS.finance;
  }
  if (lower.includes("growth") || lower.includes("media") || lower.includes("pr")) {
    return DEPARTMENT_POSITIONS.marketing;
  }
  if (lower.includes("biz") || lower.includes("revenue")) {
    return DEPARTMENT_POSITIONS.sales;
  }

  return DEFAULT_POSITIONS;
}


