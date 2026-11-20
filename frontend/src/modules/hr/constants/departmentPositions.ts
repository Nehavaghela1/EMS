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
 * Recommended Standard Positions by Industry Preset.
 * Gives employees standard designations appropriate for their company's industry.
 */
export const INDUSTRY_POSITIONS: Record<string, string[]> = {
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
    "Cloud Solutions Architect",
    "UI/UX Designer",
    "Product Manager",
    "Technical Support Engineer",
    "Security Analyst",
    "IT Support Specialist",
  ],
  manufacturing: [
    "Production Supervisor",
    "Plant Operations Manager",
    "Quality Control (QC) Inspector",
    "Quality Assurance Specialist",
    "Supply Chain Coordinator",
    "Maintenance Engineer",
    "Safety & EHS Officer",
    "Inventory & Warehouse Manager",
    "Procurement Specialist",
    "Mechanical Engineer",
    "Production Planner",
  ],
  healthcare: [
    "Clinical Coordinator",
    "Staff Nurse",
    "Chief Medical Officer / Physician",
    "Pharmacist",
    "Medical Laboratory Technician",
    "Healthcare Administrator",
    "Billing & Insurance Specialist",
    "Patient Care Coordinator",
    "Quality & Accreditation Officer",
  ],
  retail: [
    "Store Manager",
    "Assistant Store Manager",
    "Sales Associate / Cashier",
    "Merchandiser",
    "Inventory Controller",
    "Supply Chain Associate",
    "Visual Merchandising Specialist",
    "Customer Support Specialist",
    "E-Commerce Operations Coordinator",
  ],
  banking: [
    "Branch Relationship Manager",
    "Credit Analyst",
    "Financial Analyst",
    "Risk & Compliance Officer",
    "Loan Officer",
    "Investment Advisor",
    "Internal Auditor",
    "Operations Officer",
    "Wealth Management Specialist",
  ],
  education: [
    "Academic Coordinator",
    "Professor / Lecturer",
    "Admissions Counselor",
    "Student Affairs Officer",
    "Curriculum Developer",
    "Administrative Officer",
    "Librarian / Resource Specialist",
    "Educational Counselor",
  ],
  hospitality: [
    "Hotel General Manager",
    "Front Desk Supervisor",
    "Guest Relations Executive",
    "Executive Chef",
    "Food & Beverage Manager",
    "Housekeeping Supervisor",
    "Event & Banquet Coordinator",
    "Catering Manager",
  ],
  construction: [
    "Project Engineer",
    "Site Supervisor / Manager",
    "Civil Engineer",
    "Safety & Compliance Manager",
    "Quantity Surveyor",
    "Draftsman / CAD Designer",
    "Procurement Coordinator",
    "Structural Engineer",
  ],
  real_estate: [
    "Real Estate Agent / Broker",
    "Property Manager",
    "Leasing Consultant",
    "Business Development Executive",
    "Real Estate Legal Advisor",
    "Valuation Analyst",
    "Portfolio Manager",
  ],
  logistics: [
    "Fleet Operations Manager",
    "Warehouse Supervisor",
    "Logistics Coordinator",
    "Dispatch Specialist",
    "Freight Forwarder",
    "Inventory Controller",
    "Route Optimization Specialist",
    "Customs Clearance Executive",
  ],
  media: [
    "Content Strategist / Copywriter",
    "Creative Director",
    "Video Producer / Editor",
    "Graphic / Visual Designer",
    "Digital Marketing Manager",
    "Public Relations Specialist",
    "Social Media Manager",
    "Sound & Media Technician",
  ],
  non_profit: [
    "Program Director / Manager",
    "Fundraising & Development Coordinator",
    "Grant Writer",
    "Community Outreach Officer",
    "Volunteer Coordinator",
    "Monitoring & Evaluation Specialist",
  ],
};

/**
 * Returns the recommended standard positions matching a company industry name.
 */
export function getPositionsForIndustry(industryName: string | null | undefined): string[] {
  if (!industryName) return DEFAULT_POSITIONS;
  const lower = industryName.toLowerCase();

  for (const [key, positions] of Object.entries(INDUSTRY_POSITIONS)) {
    if (lower.includes(key)) {
      return positions;
    }
  }

  // Common aliases
  if (lower.includes("tech") || lower.includes("software") || lower.includes("it") || lower.includes("saas")) {
    return INDUSTRY_POSITIONS.technology;
  }
  if (lower.includes("finance") || lower.includes("bank") || lower.includes("fintech") || lower.includes("invest")) {
    return INDUSTRY_POSITIONS.banking;
  }
  if (lower.includes("hospital") || lower.includes("health") || lower.includes("pharma") || lower.includes("medic")) {
    return INDUSTRY_POSITIONS.healthcare;
  }
  if (lower.includes("manufactur") || lower.includes("factory") || lower.includes("plant") || lower.includes("industrial")) {
    return INDUSTRY_POSITIONS.manufacturing;
  }
  if (lower.includes("transport") || lower.includes("freight") || lower.includes("supply")) {
    return INDUSTRY_POSITIONS.logistics;
  }
  if (lower.includes("property") || lower.includes("estate")) {
    return INDUSTRY_POSITIONS.real_estate;
  }
  if (lower.includes("school") || lower.includes("college") || lower.includes("universit")) {
    return INDUSTRY_POSITIONS.education;
  }
  if (lower.includes("entertain") || lower.includes("film") || lower.includes("broadcast")) {
    return INDUSTRY_POSITIONS.media;
  }
  if (lower.includes("charity") || lower.includes("ngo")) {
    return INDUSTRY_POSITIONS.non_profit;
  }

  return DEFAULT_POSITIONS;
}

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


