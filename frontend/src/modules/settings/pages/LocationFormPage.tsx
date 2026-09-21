import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { createLocation, type CompanyLocationCreate } from "../../identity/api";
import { PageHeader } from "../../../shared/components/PageHeader";

export function LocationFormPage() {
  const navigate = useNavigate();
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [formData, setFormData] = useState<CompanyLocationCreate>({
    name: "",
    code: "",
    address_line1: "",
    city: "",
    state: "",
    country: "India",
    postal_code: "",
    is_primary: false,
    latitude: undefined,
    longitude: undefined,
    geofence_radius_meters: 150,
    is_remote_exempt: false,
  });

  const [locating, setLocating] = useState(false);

  const handleGetCurrentLocation = () => {
    if (!navigator.geolocation) {
      alert("Geolocation is not supported by your browser.");
      return;
    }
    setLocating(true);
    navigator.geolocation.getCurrentPosition(
      (pos) => {
        setFormData((prev) => ({
          ...prev,
          latitude: parseFloat(pos.coords.latitude.toFixed(6)),
          longitude: parseFloat(pos.coords.longitude.toFixed(6)),
        }));
        setLocating(false);
      },
      (err) => {
        alert(`Failed to get current location: ${err.message}`);
        setLocating(false);
      },
      { timeout: 10000, enableHighAccuracy: true }
    );
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setIsSubmitting(true);
    setError(null);
    try {
      await createLocation(formData);
      navigate("/settings/locations");
    } catch (err: any) {
      setError(err.response?.data?.detail || "Failed to create location.");
      setIsSubmitting(false);
    }
  };

  return (
    <div className="flex flex-col h-full bg-slate-50">
      <PageHeader
        title="Add New Location"
        action={
          <button
            onClick={() => navigate("/settings/locations")}
            className="inline-flex items-center gap-2 px-4 py-2 bg-white border border-slate-300 text-slate-700 text-sm font-medium rounded-lg hover:bg-slate-50 transition-colors shadow-sm"
          >
            ← Back to Locations
          </button>
        }
      />

      <div className="p-8 flex-1 overflow-auto">
        <form onSubmit={handleSubmit} className="max-w-3xl mx-auto space-y-8">
          {error && (
            <div className="p-4 rounded-xl bg-red-50 border border-red-100 text-red-600 text-sm">
              {error}
            </div>
          )}

          {/* Section 1: Basic Info */}
          <div className="bg-white rounded-xl shadow-sm border border-slate-200 overflow-hidden">
            <div className="px-6 py-4 border-b border-slate-200 bg-slate-50/50">
              <h3 className="text-base font-semibold text-slate-900">Basic Information</h3>
              <p className="text-sm text-slate-500">The primary identifiers for this branch.</p>
            </div>
            <div className="p-6 grid grid-cols-2 gap-6">
              <div className="col-span-2 sm:col-span-1">
                <label className="block text-sm font-medium text-slate-700 mb-2">Location Name *</label>
                <input
                  type="text"
                  required
                  value={formData.name}
                  onChange={(e) => setFormData({ ...formData, name: e.target.value })}
                  placeholder="e.g. Bangalore Branch"
                  className="w-full px-4 py-2.5 bg-slate-50 border border-slate-200 rounded-lg text-sm focus:ring-2 focus:ring-indigo-500 focus:border-indigo-500 outline-none transition-all"
                />
              </div>
              <div className="col-span-2 sm:col-span-1">
                <label className="block text-sm font-medium text-slate-700 mb-2">Location Code *</label>
                <input
                  type="text"
                  required
                  value={formData.code}
                  onChange={(e) => setFormData({ ...formData, code: e.target.value })}
                  placeholder="e.g. BLR-01"
                  className="w-full px-4 py-2.5 bg-slate-50 border border-slate-200 rounded-lg text-sm focus:ring-2 focus:ring-indigo-500 focus:border-indigo-500 outline-none transition-all uppercase"
                />
              </div>
              <div className="col-span-2 flex items-center gap-3">
                <input
                  type="checkbox"
                  id="is_primary"
                  checked={formData.is_primary}
                  onChange={(e) => setFormData({ ...formData, is_primary: e.target.checked })}
                  className="w-4 h-4 text-indigo-600 border-slate-300 rounded focus:ring-indigo-500"
                />
                <label htmlFor="is_primary" className="text-sm font-medium text-slate-700">
                  This is the Head Office (Primary Location)
                </label>
              </div>
            </div>
          </div>

          {/* Section 2: Address */}
          <div className="bg-white rounded-xl shadow-sm border border-slate-200 overflow-hidden">
            <div className="px-6 py-4 border-b border-slate-200 bg-slate-50/50">
              <h3 className="text-base font-semibold text-slate-900">Address Details</h3>
              <p className="text-sm text-slate-500">Physical address of this branch.</p>
            </div>
            <div className="p-6 grid grid-cols-2 gap-6">
              <div className="col-span-2">
                <label className="block text-sm font-medium text-slate-700 mb-2">Address Line 1</label>
                <input
                  type="text"
                  value={formData.address_line1 || ""}
                  onChange={(e) => setFormData({ ...formData, address_line1: e.target.value })}
                  placeholder="Street address, building, unit"
                  className="w-full px-4 py-2.5 bg-slate-50 border border-slate-200 rounded-lg text-sm focus:ring-2 focus:ring-indigo-500 focus:border-indigo-500 outline-none transition-all"
                />
              </div>
              <div className="col-span-2 sm:col-span-1">
                <label className="block text-sm font-medium text-slate-700 mb-2">City</label>
                <input
                  type="text"
                  value={formData.city || ""}
                  onChange={(e) => setFormData({ ...formData, city: e.target.value })}
                  className="w-full px-4 py-2.5 bg-slate-50 border border-slate-200 rounded-lg text-sm focus:ring-2 focus:ring-indigo-500 focus:border-indigo-500 outline-none transition-all"
                />
              </div>
              <div className="col-span-2 sm:col-span-1">
                <label className="block text-sm font-medium text-slate-700 mb-2">State / Province</label>
                <input
                  type="text"
                  value={formData.state || ""}
                  onChange={(e) => setFormData({ ...formData, state: e.target.value })}
                  className="w-full px-4 py-2.5 bg-slate-50 border border-slate-200 rounded-lg text-sm focus:ring-2 focus:ring-indigo-500 focus:border-indigo-500 outline-none transition-all"
                />
              </div>
              <div className="col-span-2 sm:col-span-1">
                <label className="block text-sm font-medium text-slate-700 mb-2">Postal Code</label>
                <input
                  type="text"
                  value={formData.postal_code || ""}
                  onChange={(e) => setFormData({ ...formData, postal_code: e.target.value })}
                  className="w-full px-4 py-2.5 bg-slate-50 border border-slate-200 rounded-lg text-sm focus:ring-2 focus:ring-indigo-500 focus:border-indigo-500 outline-none transition-all"
                />
              </div>
              <div className="col-span-2 sm:col-span-1">
                <label className="block text-sm font-medium text-slate-700 mb-2">Country</label>
                <input
                  type="text"
                  value={formData.country || ""}
                  onChange={(e) => setFormData({ ...formData, country: e.target.value })}
                  className="w-full px-4 py-2.5 bg-slate-50 border border-slate-200 rounded-lg text-sm focus:ring-2 focus:ring-indigo-500 focus:border-indigo-500 outline-none transition-all"
                />
              </div>
            </div>
          </div>

          {/* Section 3: GPS Geofencing */}
          <div className="bg-white rounded-xl shadow-sm border border-slate-200 overflow-hidden">
            <div className="px-6 py-4 border-b border-slate-200 bg-slate-50/50 flex justify-between items-center">
              <div>
                <h3 className="text-base font-semibold text-slate-900">GPS Geofencing</h3>
                <p className="text-sm text-slate-500">Restricts employee web check-in to this physical perimeter.</p>
              </div>
              <button
                type="button"
                onClick={handleGetCurrentLocation}
                disabled={locating}
                className="inline-flex items-center gap-2 px-3 py-1.5 text-xs font-semibold text-indigo-700 bg-indigo-50 border border-indigo-200 rounded-lg hover:bg-indigo-100 transition-colors"
              >
                <span>📍</span> {locating ? "Detecting..." : "Detect Current Coords"}
              </button>
            </div>
            <div className="p-6 grid grid-cols-2 gap-6">
              <div className="col-span-2 sm:col-span-1">
                <label className="block text-sm font-medium text-slate-700 mb-2">Latitude (°N)</label>
                <input
                  type="number"
                  step="any"
                  value={formData.latitude ?? ""}
                  onChange={(e) =>
                    setFormData({
                      ...formData,
                      latitude: e.target.value !== "" ? parseFloat(e.target.value) : undefined,
                    })
                  }
                  placeholder="e.g. 12.9716"
                  className="w-full px-4 py-2.5 bg-slate-50 border border-slate-200 rounded-lg text-sm focus:ring-2 focus:ring-indigo-500 focus:border-indigo-500 outline-none transition-all"
                />
              </div>
              <div className="col-span-2 sm:col-span-1">
                <label className="block text-sm font-medium text-slate-700 mb-2">Longitude (°E)</label>
                <input
                  type="number"
                  step="any"
                  value={formData.longitude ?? ""}
                  onChange={(e) =>
                    setFormData({
                      ...formData,
                      longitude: e.target.value !== "" ? parseFloat(e.target.value) : undefined,
                    })
                  }
                  placeholder="e.g. 77.5946"
                  className="w-full px-4 py-2.5 bg-slate-50 border border-slate-200 rounded-lg text-sm focus:ring-2 focus:ring-indigo-500 focus:border-indigo-500 outline-none transition-all"
                />
              </div>
              <div className="col-span-2 sm:col-span-1">
                <label className="block text-sm font-medium text-slate-700 mb-2">
                  Geofence Radius (meters)
                </label>
                <input
                  type="number"
                  min="20"
                  max="10000"
                  value={formData.geofence_radius_meters ?? 150}
                  onChange={(e) =>
                    setFormData({
                      ...formData,
                      geofence_radius_meters: e.target.value !== "" ? parseInt(e.target.value, 10) : 150,
                    })
                  }
                  placeholder="Default: 150m"
                  className="w-full px-4 py-2.5 bg-slate-50 border border-slate-200 rounded-lg text-sm focus:ring-2 focus:ring-indigo-500 focus:border-indigo-500 outline-none transition-all"
                />
                <span className="text-xs text-slate-500 mt-1 block">
                  Recommended: 100m – 300m to account for GPS drift indoors.
                </span>
              </div>
              <div className="col-span-2 sm:col-span-1 flex items-center pt-6">
                <div className="flex items-center gap-3">
                  <input
                    type="checkbox"
                    id="is_remote_exempt"
                    checked={formData.is_remote_exempt || false}
                    onChange={(e) => setFormData({ ...formData, is_remote_exempt: e.target.checked })}
                    className="w-4 h-4 text-indigo-600 border-slate-300 rounded focus:ring-indigo-500"
                  />
                  <label htmlFor="is_remote_exempt" className="text-sm font-medium text-slate-700">
                    Exempt this branch from geofence (Remote / Virtual Branch)
                  </label>
                </div>
              </div>
            </div>
          </div>

          <div className="flex justify-end gap-3 pt-4 border-t border-slate-200">
            <button
              type="button"
              onClick={() => navigate("/settings/locations")}
              className="px-6 py-2.5 text-sm font-medium text-slate-600 bg-white border border-slate-300 rounded-lg hover:bg-slate-50 transition-colors"
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={isSubmitting}
              className="px-6 py-2.5 text-sm font-medium text-white bg-indigo-600 rounded-lg hover:bg-indigo-700 transition-colors disabled:opacity-50 disabled:cursor-not-allowed shadow-sm"
            >
              {isSubmitting ? "Saving..." : "Save Location"}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
