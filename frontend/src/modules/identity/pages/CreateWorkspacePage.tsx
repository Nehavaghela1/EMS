import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { createWorkspace, type CreateWorkspaceInput } from "../api";
import { useAuth } from "../../../app/auth-context";

export function CreateWorkspacePage() {
  const navigate = useNavigate();
  const { establishSession } = useAuth();
  const [step, setStep] = useState(1);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [formData, setFormData] = useState<CreateWorkspaceInput>({
    company_name: "",
    country: "India",
    subdomain: "",
    currency: "INR",
    timezone: "Asia/Kolkata",
    seed_departments: true,
    seed_shift: true,
  });

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (step < 3) {
      setStep(step + 1);
      return;
    }

    setIsSubmitting(true);
    setError(null);
    try {
      const response = await createWorkspace(formData);
      await establishSession(response.access_token);
      window.location.href = "/dashboard";
    } catch (err: any) {
      setError(err.response?.data?.detail || "Failed to create workspace.");
      setIsSubmitting(false);
    }
  };

  return (
    <div className="min-h-screen bg-slate-50 flex flex-col items-center justify-center py-12 px-4 sm:px-6 lg:px-8">
      <div className="w-full max-w-2xl bg-white rounded-2xl shadow-xl border border-slate-200 overflow-hidden">
        {/* Header */}
        <div className="bg-indigo-600 px-8 py-10 text-center text-white relative overflow-hidden">
          <div className="absolute inset-0 bg-[url('https://www.transparenttextures.com/patterns/cubes.png')] opacity-10 mix-blend-overlay"></div>
          <div style={{ fontSize: "3rem", marginBottom: "0.5rem" }}>🏢</div>
          <h2 className="text-3xl font-bold tracking-tight">Create New Workspace</h2>
          <p className="mt-2 text-indigo-100 max-w-md mx-auto">
            Set up a completely new, isolated company tenant in seconds.
          </p>
        </div>

        {/* Progress Bar */}
        <div className="bg-slate-100 h-1.5 flex">
          <div className={`h-full bg-indigo-500 transition-all duration-500 ${step >= 1 ? 'w-1/3' : 'w-0'}`}></div>
          <div className={`h-full bg-indigo-500 transition-all duration-500 ${step >= 2 ? 'w-1/3' : 'w-0'}`}></div>
          <div className={`h-full bg-indigo-500 transition-all duration-500 ${step >= 3 ? 'w-1/3' : 'w-0'}`}></div>
        </div>

        {/* Form Content */}
        <form onSubmit={handleSubmit} className="p-8">
          {error && (
            <div className="mb-6 p-4 rounded-xl bg-red-50 border border-red-100 text-red-600 text-sm">
              {error}
            </div>
          )}

          {/* Step 1: Legal Entity Details */}
          {step === 1 && (
            <div className="space-y-6 animate-in fade-in slide-in-from-right-4 duration-500">
              <div className="text-center mb-8">
                <h3 className="text-xl font-semibold text-slate-900">Legal Entity Details</h3>
                <p className="text-slate-500 text-sm mt-1">What is the legal name of the new company?</p>
              </div>

              <div>
                <label className="block text-sm font-medium text-slate-700 mb-2">Company Name *</label>
                <input
                  type="text"
                  required
                  autoFocus
                  value={formData.company_name}
                  onChange={(e) => setFormData({ ...formData, company_name: e.target.value })}
                  placeholder="e.g. Infiria Tech Pvt Ltd"
                  className="w-full px-4 py-3 bg-slate-50 border border-slate-200 rounded-xl text-sm focus:ring-2 focus:ring-indigo-500 focus:border-indigo-500 outline-none transition-all"
                />
              </div>
              
              <div>
                <label className="block text-sm font-medium text-slate-700 mb-2">Company Email (Optional)</label>
                <input
                  type="email"
                  value={formData.company_email || ""}
                  onChange={(e) => setFormData({ ...formData, company_email: e.target.value })}
                  placeholder="admin@company.com"
                  className="w-full px-4 py-3 bg-slate-50 border border-slate-200 rounded-xl text-sm focus:ring-2 focus:ring-indigo-500 focus:border-indigo-500 outline-none transition-all"
                />
              </div>

              <div className="grid grid-cols-2 gap-4">
                <div>
                  <label className="block text-sm font-medium text-slate-700 mb-2">Country</label>
                  <select
                    value={formData.country}
                    onChange={(e) => setFormData({ ...formData, country: e.target.value })}
                    className="w-full px-4 py-3 bg-slate-50 border border-slate-200 rounded-xl text-sm focus:ring-2 focus:ring-indigo-500 focus:border-indigo-500 outline-none transition-all"
                  >
                    <option value="India">India</option>
                    <option value="United States">United States</option>
                    <option value="United Kingdom">United Kingdom</option>
                    <option value="Singapore">Singapore</option>
                    <option value="Australia">Australia</option>
                  </select>
                </div>
                <div>
                  <label className="block text-sm font-medium text-slate-700 mb-2">Workspace Subdomain</label>
                  <div className="flex items-center rounded-xl overflow-hidden border border-slate-200 focus-within:ring-2 focus-within:ring-indigo-500 focus-within:border-indigo-500 transition-all bg-slate-50">
                    <input
                      type="text"
                      value={formData.subdomain || ""}
                      onChange={(e) => setFormData({ ...formData, subdomain: e.target.value })}
                      placeholder="acme"
                      className="w-full px-4 py-3 bg-transparent text-sm outline-none"
                    />
                    <span className="px-4 py-3 bg-slate-100 text-slate-500 text-sm border-l border-slate-200">.ems.dev</span>
                  </div>
                </div>
              </div>
            </div>
          )}

          {/* Step 2: Regional Defaults */}
          {step === 2 && (
            <div className="space-y-6 animate-in fade-in slide-in-from-right-4 duration-500">
              <div className="text-center mb-8">
                <h3 className="text-xl font-semibold text-slate-900">Regional Settings</h3>
                <p className="text-slate-500 text-sm mt-1">Set the default currency and timezone for this tenant.</p>
              </div>

              <div className="grid grid-cols-2 gap-6">
                <div>
                  <label className="block text-sm font-medium text-slate-700 mb-2">Base Currency</label>
                  <select
                    value={formData.currency}
                    onChange={(e) => setFormData({ ...formData, currency: e.target.value })}
                    className="w-full px-4 py-3 bg-slate-50 border border-slate-200 rounded-xl text-sm focus:ring-2 focus:ring-indigo-500 focus:border-indigo-500 outline-none transition-all"
                  >
                    <option value="INR">₹ INR - Indian Rupee</option>
                    <option value="USD">$ USD - US Dollar</option>
                    <option value="EUR">€ EUR - Euro</option>
                    <option value="GBP">£ GBP - British Pound</option>
                    <option value="SGD">$ SGD - Singapore Dollar</option>
                  </select>
                </div>
                <div>
                  <label className="block text-sm font-medium text-slate-700 mb-2">Timezone</label>
                  <select
                    value={formData.timezone}
                    onChange={(e) => setFormData({ ...formData, timezone: e.target.value })}
                    className="w-full px-4 py-3 bg-slate-50 border border-slate-200 rounded-xl text-sm focus:ring-2 focus:ring-indigo-500 focus:border-indigo-500 outline-none transition-all"
                  >
                    <option value="Asia/Kolkata">Asia/Kolkata (IST)</option>
                    <option value="America/New_York">America/New_York (EST)</option>
                    <option value="Europe/London">Europe/London (GMT)</option>
                    <option value="Asia/Singapore">Asia/Singapore (SGT)</option>
                  </select>
                </div>
              </div>
              
              <div className="mt-8 p-6 bg-blue-50 border border-blue-100 rounded-xl">
                <div className="flex items-start gap-4">
                  <span style={{ fontSize: "1.5rem" }}>🏢</span>
                  <div>
                    <h4 className="text-sm font-semibold text-blue-900">Head Office Auto-Provisioning</h4>
                    <p className="text-sm text-blue-700 mt-1 leading-relaxed">
                      We will automatically create a "Head Office" location for this workspace based on the country provided. You can edit the exact address in Settings &gt; Work Locations later.
                    </p>
                  </div>
                </div>
              </div>
            </div>
          )}

          {/* Step 3: Starter Defaults */}
          {step === 3 && (
            <div className="space-y-6 animate-in fade-in slide-in-from-right-4 duration-500">
              <div className="text-center mb-8">
                <h3 className="text-xl font-semibold text-slate-900">Starter Defaults</h3>
                <p className="text-slate-500 text-sm mt-1">Pre-fill the workspace with standard configurations.</p>
              </div>

              <label className="flex items-start gap-4 p-5 rounded-xl border border-slate-200 cursor-pointer hover:border-indigo-300 hover:bg-indigo-50/30 transition-colors">
                <div className="pt-0.5">
                  <input
                    type="checkbox"
                    checked={formData.seed_departments}
                    onChange={(e) => setFormData({ ...formData, seed_departments: e.target.checked })}
                    className="w-5 h-5 text-indigo-600 border-slate-300 rounded focus:ring-indigo-500"
                  />
                </div>
                <div>
                  <p className="text-sm font-semibold text-slate-900">Seed Standard Departments</p>
                  <p className="text-sm text-slate-500 mt-1">Automatically create Engineering, Sales, HR, and Finance departments.</p>
                </div>
              </label>

              <label className="flex items-start gap-4 p-5 rounded-xl border border-slate-200 cursor-pointer hover:border-indigo-300 hover:bg-indigo-50/30 transition-colors">
                <div className="pt-0.5">
                  <input
                    type="checkbox"
                    checked={formData.seed_shift}
                    onChange={(e) => setFormData({ ...formData, seed_shift: e.target.checked })}
                    className="w-5 h-5 text-indigo-600 border-slate-300 rounded focus:ring-indigo-500"
                  />
                </div>
                <div>
                  <p className="text-sm font-semibold text-slate-900">Seed Default Shift</p>
                  <p className="text-sm text-slate-500 mt-1">Automatically create a standard 9:00 AM - 6:00 PM General Shift.</p>
                </div>
              </label>
            </div>
          )}

          {/* Navigation Controls */}
          <div className="mt-10 pt-6 border-t border-slate-100 flex items-center justify-between">
            <button
              type="button"
              onClick={() => step > 1 ? setStep(step - 1) : navigate(-1)}
              className="px-6 py-2.5 text-sm font-medium text-slate-600 hover:text-slate-900 hover:bg-slate-100 rounded-lg transition-colors"
            >
              {step > 1 ? "Back" : "Cancel"}
            </button>
            <button
              type="submit"
              disabled={isSubmitting || (step === 1 && !formData.company_name)}
              className="px-8 py-2.5 bg-indigo-600 text-white text-sm font-medium rounded-lg hover:bg-indigo-700 transition-colors shadow-md flex items-center gap-2 disabled:opacity-50 disabled:cursor-not-allowed"
            >
              {step < 3 ? (
                <>Next Step →</>
              ) : isSubmitting ? (
                "Creating Workspace..."
              ) : (
                "Launch Workspace"
              )}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
