import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { listLocations, type CompanyLocation } from "../../identity/api";
import { PageHeader } from "../../../shared/components/PageHeader";

export function LocationListPage() {
  const [locations, setLocations] = useState<CompanyLocation[]>([]);
  const [isLoading, setIsLoading] = useState(true);

  useEffect(() => {
    async function load() {
      try {
        const data = await listLocations();
        setLocations(data);
      } catch (error) {
        console.error("Failed to load locations", error);
      } finally {
        setIsLoading(false);
      }
    }
    load();
  }, []);

  return (
    <div className="flex flex-col h-full bg-slate-50">
      <PageHeader
        title="Work Locations"
        action={
          <Link
            to="/settings/locations/new"
            className="inline-flex items-center gap-2 px-4 py-2 bg-indigo-600 text-white text-sm font-medium rounded-lg hover:bg-indigo-700 transition-colors shadow-sm"
          >
            <span>+</span> Add Location
          </Link>
        }
      />

      <div className="p-8 flex-1 overflow-auto">
        <div className="max-w-6xl mx-auto bg-white rounded-xl shadow-sm border border-slate-200 overflow-hidden">
          <table className="w-full text-left text-sm">
            <thead className="bg-slate-50 border-b border-slate-200 text-slate-600 font-medium">
              <tr>
                <th className="px-6 py-4">Name</th>
                <th className="px-6 py-4">Code</th>
                <th className="px-6 py-4">Address</th>
                <th className="px-6 py-4">Primary</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {isLoading ? (
                <tr>
                  <td colSpan={4} className="px-6 py-8 text-center text-slate-400">
                    Loading locations...
                  </td>
                </tr>
              ) : locations.length === 0 ? (
                <tr>
                  <td colSpan={4} className="px-6 py-12 text-center">
                    <div style={{ fontSize: "2.5rem", marginBottom: "0.5rem" }}>🏢</div>
                    <p className="text-slate-500 font-medium">No locations found</p>
                    <p className="text-slate-400 mt-1">Get started by creating your first branch.</p>
                  </td>
                </tr>
              ) : (
                locations.map((loc) => (
                  <tr key={loc.id} className="hover:bg-slate-50 transition-colors">
                    <td className="px-6 py-4">
                      <p className="font-medium text-slate-900">{loc.name}</p>
                    </td>
                    <td className="px-6 py-4">
                      <span className="inline-flex px-2 py-1 bg-slate-100 text-slate-700 text-xs font-medium rounded-md">
                        {loc.code}
                      </span>
                    </td>
                    <td className="px-6 py-4">
                      <p className="text-slate-600">
                        {[loc.address_line1, loc.city, loc.state].filter(Boolean).join(", ") ||
                          "No address provided"}
                      </p>
                      <p className="text-slate-400 text-xs mt-0.5">{loc.country}</p>
                    </td>
                    <td className="px-6 py-4">
                      {loc.is_primary ? (
                        <span className="inline-flex px-2.5 py-1 bg-indigo-50 text-indigo-700 text-xs font-medium rounded-full border border-indigo-100">
                          Head Office
                        </span>
                      ) : (
                        <span className="text-slate-400 text-sm">—</span>
                      )}
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
