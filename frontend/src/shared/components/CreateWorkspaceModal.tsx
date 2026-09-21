import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import { createWorkspace, type CreateWorkspaceInput } from "../../modules/identity/api";
import { useAuth } from "../../app/auth-context";

interface Props {
  isOpen: boolean;
  onClose: () => void;
}

export function CreateWorkspaceModal({ isOpen, onClose }: Props) {
  const [step, setStep] = useState<1 | 2>(1);
  const { establishSession } = useAuth();
  const queryClient = useQueryClient();
  const navigate = useNavigate();

  // Form State
  const [companyName, setCompanyName] = useState("");
  const [companyEmail, setCompanyEmail] = useState("");
  const [subdomain, setSubdomain] = useState("");
  const [country, setCountry] = useState("IN");
  const [seedDefaults, setSeedDefaults] = useState(true);

  const mutation = useMutation({
    mutationFn: (data: CreateWorkspaceInput) => createWorkspace(data),
    onSuccess: async (data) => {
      // Clear React Query cache entirely so previous tenant's data isn't shown
      queryClient.clear();
      
      // Update auth context with new scoped JWT
      await establishSession(data.access_token);
      
      // Close modal and navigate to the dashboard
      onClose();
      navigate("/dashboard");
    },
  });

  const handleNext = () => {
    if (companyName.trim()) setStep(2);
  };

  const handleCreate = () => {
    mutation.mutate({
      company_name: companyName,
      company_email: companyEmail || undefined,
      subdomain: subdomain || undefined,
      country,
      seed_departments: seedDefaults,
      seed_shift: seedDefaults,
    });
  };

  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 z-50 overflow-hidden">
      <div className="absolute inset-0 bg-slate-900/50 backdrop-blur-sm transition-opacity" onClick={onClose} />
      <div className="fixed inset-y-0 right-0 max-w-md w-full bg-white shadow-2xl flex flex-col transform transition-transform duration-300 ease-in-out translate-x-0">
        {/* Header */}
        <div className="px-6 py-4 border-b flex items-center justify-between bg-white">
          <h2 className="text-lg font-semibold text-slate-800">
            {step === 1 ? "Create New Workspace" : "Workspace Settings"}
          </h2>
          <button 
            onClick={onClose}
            className="text-slate-400 hover:text-slate-600 transition-colors p-1"
          >
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <line x1="18" y1="6" x2="6" y2="18"></line>
              <line x1="6" y1="6" x2="18" y2="18"></line>
            </svg>
          </button>
        </div>

        {/* Body */}
        <div className="p-6 flex-1 overflow-y-auto bg-white">
          {step === 1 ? (
            <div className="space-y-5">
              <div>
                <label className="block text-sm font-medium text-slate-700 mb-1">Company Legal Name *</label>
                <input 
                  type="text"
                  value={companyName}
                  onChange={(e) => setCompanyName(e.target.value)}
                  placeholder="e.g. Acme Innovations Pvt Ltd"
                  className="w-full rounded-md border border-slate-300 px-3 py-2.5 text-sm focus:border-indigo-500 focus:outline-none focus:ring-1 focus:ring-indigo-500 transition-shadow"
                  autoFocus
                />
              </div>
              
              <div>
                <label className="block text-sm font-medium text-slate-700 mb-1">Company Email <span className="text-slate-400 font-normal">(Optional)</span></label>
                <input 
                  type="email"
                  value={companyEmail}
                  onChange={(e) => setCompanyEmail(e.target.value)}
                  placeholder="hello@acme.com"
                  className="w-full rounded-md border border-slate-300 px-3 py-2.5 text-sm focus:border-indigo-500 focus:outline-none focus:ring-1 focus:ring-indigo-500 transition-shadow"
                />
              </div>
              
              <div className="space-y-5">
                <div>
                  <label className="block text-sm font-medium text-slate-700 mb-1">Subdomain <span className="text-slate-400 font-normal">(Optional)</span></label>
                  <div className="flex items-center rounded-md border border-slate-300 px-3 py-2.5 focus-within:border-indigo-500 focus-within:ring-1 focus-within:ring-indigo-500 bg-white transition-shadow">
                    <input 
                      type="text"
                      value={subdomain}
                      onChange={(e) => setSubdomain(e.target.value)}
                      placeholder="acme"
                      className="w-full border-none p-0 text-sm focus:outline-none focus:ring-0 bg-transparent"
                    />
                    <span className="text-slate-400 text-sm ml-2 bg-slate-50 px-2 py-0.5 rounded border">.ems.com</span>
                  </div>
                </div>
                <div>
                  <label className="block text-sm font-medium text-slate-700 mb-1">Country</label>
                  <select 
                    value={country}
                    onChange={(e) => setCountry(e.target.value)}
                    className="w-full rounded-md border border-slate-300 px-3 py-2.5 text-sm bg-white focus:border-indigo-500 focus:outline-none focus:ring-1 focus:ring-indigo-500 transition-shadow"
                  >
                    <option value="IN">India</option>
                    <option value="US">United States</option>
                    <option value="UK">United Kingdom</option>
                  </select>
                </div>
              </div>
            </div>
          ) : (
            <div className="space-y-5">
              <div className="bg-indigo-50/50 border border-indigo-100 p-4 rounded-xl flex items-start space-x-3">
                <input
                  type="checkbox"
                  id="seedDefaults"
                  checked={seedDefaults}
                  onChange={(e) => setSeedDefaults(e.target.checked)}
                  className="mt-1 rounded text-indigo-600 focus:ring-indigo-500 h-4 w-4 cursor-pointer"
                />
                <div>
                  <label htmlFor="seedDefaults" className="text-sm font-medium text-indigo-900 block cursor-pointer">
                    Seed Workspace with Defaults
                  </label>
                  <p className="text-sm text-indigo-700 mt-1 leading-relaxed">
                    Automatically create standard departments (Engineering, HR, Sales, Finance) and a default General Shift (09:00 - 18:00) so you can start adding employees right away.
                  </p>
                </div>
              </div>

              <div className="bg-slate-50 border p-4 rounded-xl">
                <h4 className="text-sm font-medium text-slate-800 mb-1 flex items-center gap-2">
                  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                    <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/>
                  </svg>
                  Permissions
                </h4>
                <p className="text-sm text-slate-600 leading-relaxed mt-2">
                  You will automatically be assigned as the <strong>Workspace Owner (HR Admin)</strong> for this new company, keeping your existing login email and password.
                </p>
              </div>
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="px-6 py-4 border-t bg-slate-50 flex items-center justify-between">
          {step === 2 ? (
            <button 
              onClick={() => setStep(1)}
              className="px-4 py-2 text-sm font-medium text-slate-600 hover:text-slate-900 transition-colors"
            >
              Back
            </button>
          ) : (
            <div /> // placeholder for spacing
          )}
          
          <div className="flex items-center space-x-3">
            <button 
              onClick={onClose}
              className="px-4 py-2 text-sm font-medium text-slate-600 hover:bg-slate-100 rounded-md transition-colors"
            >
              Cancel
            </button>
            {step === 1 ? (
              <button 
                onClick={handleNext}
                disabled={!companyName.trim()}
                className="px-4 py-2 text-sm font-medium text-white bg-indigo-600 hover:bg-indigo-700 rounded-md shadow-sm transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
              >
                Continue
              </button>
            ) : (
              <button 
                onClick={handleCreate}
                disabled={mutation.isPending}
                className="px-4 py-2 text-sm font-medium text-white bg-indigo-600 hover:bg-indigo-700 rounded-md shadow-sm transition-colors flex items-center space-x-2 disabled:opacity-70 disabled:cursor-wait"
              >
                {mutation.isPending && (
                  <svg className="animate-spin h-4 w-4 text-white" fill="none" viewBox="0 0 24 24">
                    <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"></circle>
                    <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
                  </svg>
                )}
                <span>{mutation.isPending ? "Creating..." : "Create Workspace"}</span>
              </button>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
